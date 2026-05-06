"""Concurrent multi-URL mission runner.

One `MissionRunner` instance owns one mission. The runner spawns N
per-task coroutines inside one `asyncio.TaskGroup` (invariant 3); each
coroutine runs a single `agent.run(url)` against its URL and emits its
own `task_start` / `task_end` events. After the group exits, the runner
computes the rolled-up mission status and emits the `done` event.

Per-mission semaphores (HTTP-20 / browser-3) layer over Spec 09's
process-wide ceilings (60 / 8); tier tools resolve them via the
`contextvars`-backed binding from `app.concurrency`.

Cancellation mechanic (Spec 14 plugs a user-facing endpoint into this):
- `request_cancellation()` sets an `asyncio.Event`.
- Tasks check the event at entry; tasks that haven't started yet exit
  with `Status.CANCELLED` instead of running the agent.
- Tasks already mid-flight finish normally — pending cancellation is
  not a mid-page-render kill (architecture decision in
  `progress-tracker.md` Open Question 1).
- If Spec 14 also calls `task.cancel()`, the resulting `CancelledError`
  is observed in `_run_task`'s except clause: a terminal `task_end`
  with `cancelled` status is emitted before the exception re-raises
  (invariant 5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.agent import MissionDeps, MissionResult, build_agent
from app.concurrency import MissionSemaphores, with_mission_semaphores
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import start_mission_trace
from app.persistence.models import Mission, MissionMode, Status, Task, Tier
from app.persistence.repository import MissionRepository, TaskRepository
from app.runner_helpers import (
    compute_mission_status_from_db,
    emit_mission_terminal,
    last_ok_tool_call,
)
from app.security import CurrentUser, _current_user, assert_safe_url
from app.sse import emitter
from autumn_sse_protocol import SseEvent

log = logging.getLogger(__name__)

_MAX_URLS_PER_MISSION = 20
_PREVIEW_CHARS = 500


class MissionRunner:
    """Runs one mission with N tasks under a single TaskGroup."""

    def __init__(
        self,
        *,
        user: CurrentUser,
        mission: Mission,
        tasks: list[Task],
    ) -> None:
        self._user = user
        self._mission = mission
        self._tasks = tasks
        self._sems = MissionSemaphores.fresh()
        self._cancellation_requested = asyncio.Event()
        self._missions_repo = MissionRepository()
        self._tasks_repo = TaskRepository()
        self._chain = LLMProviderChain(
            primary=OpenRouterProvider(),
            fallback=GroqProvider(),
        )

    def request_cancellation(self) -> None:
        """Mark the mission for cancellation. Tasks not yet started settle
        as `CANCELLED`; in-flight tasks finish naturally. Spec 14 wires a
        user-facing endpoint into this method.
        """
        self._cancellation_requested.set()

    async def run(self) -> None:
        """Run all tasks under one TaskGroup; emit per-task and mission
        terminal events.

        The outer `with_mission_semaphores` binds the per-mission
        ceilings to every task's `contextvars` context (TaskGroup
        propagates context across `create_task`). The inner TaskGroup
        owns the per-task coroutines (invariant 3); on exit it has
        awaited every task to a settled state.
        """
        _current_user.set(self._user)
        trace = start_mission_trace(
            mission_id=self._mission.id,
            user_id=self._user.user_id,
            prompt="\n".join(t.url for t in self._tasks),
        )

        async with with_mission_semaphores(self._sems):
            try:
                async with asyncio.TaskGroup() as tg:
                    for task in self._tasks:
                        tg.create_task(
                            self._run_task(task),
                            name=f"task:{task.id}",
                        )
            except* Exception as eg:
                # Per-task coroutines emit their own error/task_end
                # before raising; the group surfaces the aggregate so we
                # log it for observability. The mission-level rollup
                # below still runs because the `except*` does not
                # propagate.
                log.exception(
                    "mission.task_group_raised",
                    extra={
                        "mission_id": str(self._mission.id),
                        "errors": [repr(e) for e in eg.exceptions],
                    },
                )

        final_status = await compute_mission_status_from_db(self._mission.id, self._tasks_repo)
        await self._missions_repo.update_status(self._mission.id, final_status)
        await emit_mission_terminal(emitter, mission_id=self._mission.id, status=final_status)
        trace.update(output={"status": final_status.value})

    async def _run_task(self, task: Task) -> None:
        """Run one URL through one agent.run; emit terminal events.

        Invariants enforced here:
        - 5 — every code path emits exactly one task-level terminal
          (`task_end` with succeeded/failed/cancelled, or an `error`
          plus `task_end`).
        - 7 — task row flips PENDING → RUNNING before `task_start`.
        - 10 — mission-row status re-checked just before any tool
          egress so a cancellation between mission-row write and the
          first fetch doesn't race past the gate.
        """
        if self._cancellation_requested.is_set():
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            return

        # Invariant 7: task row was PENDING from `start_url_mission`.
        await self._tasks_repo.update(task.id, status=Status.RUNNING)
        await self._emit_task_start(task)

        # Invariant 10: bail if the mission row is no longer RUNNING.
        fresh = await self._missions_repo.get(self._mission.id)
        if fresh is None or fresh.status != Status.RUNNING:
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            return

        deps = MissionDeps(
            user_id=self._user.user_id,
            mission_id=self._mission.id,
            task_id=task.id,
            robots_override=self._mission.robots_override,
        )
        agent = build_agent()

        try:

            async def _run(model: Any) -> Any:
                return await agent.run(task.url, model=model, deps=deps)

            result = await self._chain.with_fallback(_run)
        except asyncio.CancelledError:
            # Invariant 5: emit terminal then re-raise so the TaskGroup
            # can surface the cancellation to the parent.
            await self._tasks_repo.update(task.id, status=Status.CANCELLED)
            await self._emit_task_end(task, status=Status.CANCELLED)
            raise
        except Exception as exc:
            log.exception(
                "task.failed",
                extra={
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                },
            )
            await self._tasks_repo.update(task.id, status=Status.FAILED)
            await self._emit_error(task, code="agent_failed", message=str(exc))
            await self._emit_task_end(task, status=Status.FAILED)
            return

        ok_call = last_ok_tool_call(result)
        mission_result: MissionResult = result.output
        succeeded = mission_result.status == "ok"
        final_status = Status.SUCCEEDED if succeeded else Status.FAILED

        await self._tasks_repo.update(
            task.id,
            status=final_status,
            latency_ms=ok_call.latency_ms if ok_call else None,
            parsed_markdown=ok_call.markdown if ok_call else None,
            snapshot_key=ok_call.snapshot_key if ok_call else None,
            snapshot_truncated=ok_call.snapshot_truncated if ok_call else False,
        )

        if mission_result.status == "error":
            error_content: dict[str, Any] = {
                "code": mission_result.error_code or "agent_failed",
                "message": mission_result.summary,
            }
            if mission_result.detected_protections:
                error_content["detected_protections"] = mission_result.detected_protections
            await self._emit_error(
                task,
                code=error_content["code"],
                message=error_content["message"],
            )

        await self._emit_task_end(task, status=final_status, ok_call=ok_call)

    async def _emit_task_start(self, task: Task) -> None:
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "task_start",
                    "content": {"url": task.url, "tier": Tier.HTTP.value},
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )

    async def _emit_task_end(
        self,
        task: Task,
        *,
        status: Status,
        ok_call: Any = None,
    ) -> None:
        sse_status = _TASK_STATUS_MAP[status]
        content: dict[str, Any] = {"status": sse_status}
        if ok_call is not None:
            content["preview"] = (ok_call.markdown or "")[:_PREVIEW_CHARS]
            if ok_call.snapshot_key:
                content["snapshot_key"] = ok_call.snapshot_key
            if ok_call.latency_ms is not None:
                content["latency_ms"] = ok_call.latency_ms
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "task_end",
                    "content": content,
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )

    async def _emit_error(self, task: Task, *, code: str, message: str) -> None:
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "error",
                    "content": {"code": code, "message": message},
                    "mission_id": str(self._mission.id),
                    "task_id": str(task.id),
                    "seq": 0,
                }
            )
        )


_TASK_STATUS_MAP: dict[Status, str] = {
    Status.SUCCEEDED: "succeeded",
    Status.FAILED: "failed",
    Status.CANCELLED: "cancelled",
}


async def start_url_mission(*, user: CurrentUser, urls: Sequence[str]) -> UUID:
    """Persist mission and N task rows; hand the runner off to the
    lifespan-scoped TaskGroup; return the mission_id immediately.

    Validates `1 ≤ len(urls) ≤ 20` and runs `assert_safe_url` on every
    URL before any DB write (invariant 1 must hold across the whole
    fan-out, not just the first task).
    """
    if not 1 <= len(urls) <= _MAX_URLS_PER_MISSION:
        raise ValueError(f"urls must contain between 1 and {_MAX_URLS_PER_MISSION} entries")
    for url in urls:
        assert_safe_url(url)

    _current_user.set(user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()

    mission = await missions_repo.create(
        prompt="\n".join(urls),
        mode=MissionMode.URL,
    )
    await missions_repo.update_status(mission.id, Status.RUNNING)

    task_rows: list[Task] = []
    for url in urls:
        row = await tasks_repo.create(
            mission_id=mission.id,
            url=url,
            tier_used=Tier.HTTP,
        )
        task_rows.append(row)

    runner = MissionRunner(user=user, mission=mission, tasks=task_rows)
    await emitter.adopt_runner(mission.id, runner)
    return mission.id
