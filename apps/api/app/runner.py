"""Concurrent multi-URL mission runner.

One `MissionRunner` instance owns one mission. The runner spawns N
per-task coroutines inside one `asyncio.TaskGroup` (invariant 3); each
coroutine runs a single `agent.run(url)` against its URL and emits its
own `task_start` / `task_end` events. After the group exits, the runner
computes the rolled-up mission status and emits the `done` event.

Per-mission semaphores (HTTP-20 / browser-3) layer over Spec 09's
process-wide ceilings (60 / 8); tier tools resolve them via the
`contextvars`-backed binding from `app.concurrency`.

Cancellation mechanic (Spec 14 wires user-facing endpoints into this):
- `request_cancellation()` sets a mission-wide `asyncio.Event`.
- `cancel_task(task_id)` adds one task id to a per-task cancel set
  (mission-level event stays untouched — other tasks keep running).
- `_run_task` checks both flags at three step boundaries: entry,
  immediately after `task_start` emission, and just before the agent
  dispatch. A task cancelled at any boundary writes `Status.CANCELLED`
  before emitting `task_end` (invariants 5 + 7).
- Tasks already past the agent dispatch finish their network egress —
  pending cancellation is not a mid-page-render kill (architecture
  decision in `progress-tracker.md` Open Question 1).
- If the lifespan TaskGroup itself cancels (process shutdown), the
  resulting `CancelledError` is observed in `_run_task`'s except clause:
  a terminal `task_end` with `cancelled` status is emitted before the
  exception re-raises (invariant 5).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

import structlog

from app.agent import (
    DiscoveryDeps,
    DiscoveryMissionResult,
    MissionDeps,
    MissionResult,
    build_agent,
    build_discovery_agent,
)
from app.concurrency import MissionSemaphores, with_mission_semaphores
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import fetch_mission_cost_cents, start_mission_trace
from app.persistence.models import (
    Mission,
    MissionMode,
    MissionPhase,
    Status,
    Task,
    Tier,
)
from app.persistence.repository import MissionRepository, TaskRepository
from app.runner_helpers import (
    compute_mission_status_from_db,
    emit_agent_observability,
    emit_mission_terminal,
    emit_task_terminal,
    last_ok_tool_call,
)
from app.security import CurrentUser, _current_user, assert_safe_url
from app.sse import emitter
from autumn_sse_protocol import SseEvent

log = structlog.get_logger()

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
        self._cancelled_task_ids: set[UUID] = set()
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

    def cancel_task(self, task_id: UUID) -> None:
        """Mark one task for cancellation without flipping the mission
        event. Idempotent (set semantics). The task observes the flag at
        the next step boundary in `_run_task` and exits `CANCELLED`.
        """
        self._cancelled_task_ids.add(task_id)

    def _is_cancelled(self, task_id: UUID) -> bool:
        return task_id in self._cancelled_task_ids or self._cancellation_requested.is_set()

    async def _settle_cancelled(self, task: Task) -> None:
        """Atomic cancel-then-emit for a single task: write
        `Status.CANCELLED` to the row (invariant 7), then emit
        `task_end(cancelled)` (invariant 5). Used by all three cancel
        checkpoints in `_run_task` so the DB-before-SSE ordering
        cannot drift between them.
        """
        await self._tasks_repo.update(task.id, status=Status.CANCELLED)
        await self._emit_task_end(task, status=Status.CANCELLED)

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
                    mission_id=str(self._mission.id),
                    errors=[repr(e) for e in eg.exceptions],
                )

        # Spec 14: status rollup and Langfuse cost lookup are independent
        # reads — run them concurrently so the cost fetch's network
        # round-trip overlaps with the per-task DB query. The cost helper
        # bounds itself with a 5s deadline; a hung Langfuse degrades to
        # `cost_cents = 0` and the sidebar renders `?` for terminal
        # missions with zero cost.
        final_status, cost_or_none = await asyncio.gather(
            compute_mission_status_from_db(self._mission.id, self._tasks_repo),
            fetch_mission_cost_cents(self._mission.id),
        )
        cost_cents = cost_or_none or 0
        # Cost write precedes status / phase / SSE so a slide-over reattach
        # observes both the cost and the final state before the `done`
        # event arrives (invariant 7).
        await self._missions_repo.update_cost_cents(self._mission.id, cost_cents)
        await self._missions_repo.update_status(self._mission.id, final_status)
        await self._missions_repo.set_phase(self._mission.id, MissionPhase.DONE)
        await emit_mission_terminal(
            emitter,
            mission_id=self._mission.id,
            status=final_status,
            cost_cents=cost_cents,
        )
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
        # Scoped binding — sibling tasks under the same TaskGroup must not
        # see each other's ids. `contextvars` propagates across
        # `create_task` so nested tools / LLM / SSE emissions inherit.
        with structlog.contextvars.bound_contextvars(
            mission_id=str(self._mission.id),
            task_id=str(task.id),
        ):
            # Boundary 1 — pre-start: task row is still PENDING. No `task_start`
            # has been emitted; emitting `task_end` directly is the correct
            # single terminal (invariant 5).
            if self._is_cancelled(task.id):
                await self._settle_cancelled(task)
                return

            # Invariant 7: task row was PENDING from `start_url_mission`.
            await self._tasks_repo.update(task.id, status=Status.RUNNING)
            await self._emit_task_start(task)

            # Boundary 2 — between `task_start` and the invariant-10 fresh
            # read. Cancels arriving in this window still settle terminally.
            if self._is_cancelled(task.id):
                await self._settle_cancelled(task)
                return

            # Invariant 10: bail if the mission row is no longer RUNNING.
            fresh = await self._missions_repo.get(self._mission.id)
            if fresh is None or fresh.status != Status.RUNNING:
                await self._settle_cancelled(task)
                return

            # Boundary 3 — final pre-agent check. After this we hand off to
            # `agent.run`; in-flight cancels finish their network egress.
            if self._is_cancelled(task.id):
                await self._settle_cancelled(task)
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
                log.exception("task.failed")
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

            # Replay the agent's intermediate state (reasoning text, tool
            # calls, tool returns) onto SSE so the slide-over's lane log
            # shows what the agent actually did. Pydantic AI's one-shot
            # `agent.run(...)` does not stream those events; we walk the
            # message history after-the-fact and emit synthesized events
            # in chronological order. The events land before the
            # terminal `task_end` so a connected client sees the full
            # transcript before the lane settles.
            try:
                await emit_agent_observability(
                    emitter,
                    mission_id=self._mission.id,
                    task_id=task.id,
                    result=result,
                )
            except Exception:  # pragma: no cover — observability must never break the runner
                log.exception("task.observability_emit_failed")

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
        extras: dict[str, Any] = {}
        if ok_call is not None:
            extras["preview"] = (ok_call.markdown or "")[:_PREVIEW_CHARS]
            if ok_call.snapshot_key:
                extras["snapshot_key"] = ok_call.snapshot_key
            if ok_call.latency_ms is not None:
                extras["latency_ms"] = ok_call.latency_ms
        await emit_task_terminal(
            emitter,
            mission_id=self._mission.id,
            task_id=task.id,
            status=status,
            content_extras=extras or None,
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
    # URL-mode missions skip discovery; the dashboard treats every mission
    # uniformly when `phase` is non-null.
    await missions_repo.set_phase(mission.id, MissionPhase.SCRAPING)

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


# --- description-mode (Spec 12) -----------------------------------------


_DEFAULT_APPROVAL_TIMEOUT_S = 1800.0


@dataclass(slots=True)
class _PendingApproval:
    """In-memory approval state for one parked description-mode mission.

    Lives in `_pending_approvals` keyed by `mission_id`. The runner sets
    its `event` to wake; `submit_approval` carries the approved URL list
    and persistence flag across the side-channel POST handoff.
    """

    event: asyncio.Event
    approved_urls: list[str] | None = None
    skip_approval_persisted: bool = False


_pending_approvals: dict[UUID, _PendingApproval] = {}


def register_pending_approval(mission_id: UUID) -> _PendingApproval:
    """Allocate a fresh `_PendingApproval` and return the runner's handle.

    Idempotent in the sense that re-registering replaces any stale entry —
    a fresh discovery for the same mission_id is a Spec 14 concern, not
    something this spec exercises.
    """
    req = _PendingApproval(event=asyncio.Event())
    _pending_approvals[mission_id] = req
    return req


def submit_approval(
    mission_id: UUID,
    *,
    approved_urls: list[str],
    skip_approval: bool,
) -> Literal["accepted", "no_pending"]:
    """Carry the approved URL list across the SSE/REST boundary.

    Returns `"no_pending"` if no in-memory entry exists for the mission
    (the runner process restarted between discovery and approval). The
    `/approve` route maps this to a 503 so the client can retry instead
    of seeing a misleading 204. Returns `"accepted"` after setting the
    event; the runner picks up `approved_urls` and resumes.
    """
    req = _pending_approvals.get(mission_id)
    if req is None:
        return "no_pending"
    req.approved_urls = approved_urls
    req.skip_approval_persisted = skip_approval
    req.event.set()
    return "accepted"


async def wait_for_approval(mission_id: UUID, *, timeout_s: float) -> _PendingApproval | None:
    """Block until `submit_approval` fires or the timeout elapses.

    Returns the populated `_PendingApproval` on success, `None` on timeout.
    Cleans up the registry entry in `finally` so a successive mission
    cannot inherit stale approval state.
    """
    req = _pending_approvals.get(mission_id)
    if req is None:
        return None
    try:
        await asyncio.wait_for(req.event.wait(), timeout=timeout_s)
    except TimeoutError:
        return None
    finally:
        _pending_approvals.pop(mission_id, None)
    return req


@dataclass
class DescriptionMissionRunner:
    """Adapter satisfying `_RunnableMission` for `adopt_runner`.

    `adopt_runner` accepts anything with `.run() -> Awaitable[None]`; this
    dataclass wraps `run_description_mission` so the lifespan TaskGroup
    can adopt the description-mode workflow the same way it adopts a
    URL-mode `MissionRunner`.

    Spec 14 also routes user cancellation through this wrapper — the
    `cancel_mission` route looks the wrapper up via
    `emitter.get_active_runner(...)` and calls `request_cancellation()` /
    `cancel_task(task_id)` here. Both methods forward to the inner
    URL-mode `MissionRunner` once it exists; before SCRAPING (during
    DISCOVERING / AWAITING_APPROVAL) the wrapper wakes the parked
    approval with an empty URL list so the run loop exits cleanly with
    one terminal `done(cancelled)`.
    """

    user: CurrentUser
    mission: Mission
    query: str
    approval_timeout_s: float = _DEFAULT_APPROVAL_TIMEOUT_S
    # `init=False` keeps the public constructor signature unchanged; the
    # wrapper is mutated mid-flight via `set_inner_runner` and
    # `request_cancellation`.
    _inner_runner: MissionRunner | None = field(default=None, init=False, repr=False)
    _cancellation_requested: bool = field(default=False, init=False, repr=False)

    def request_cancellation(self) -> None:
        """Cancel the mission. Forwards to the inner SCRAPING-phase
        runner if present; otherwise wakes any parked approval gate. The
        cancellation flag is also set so the run loop can re-check after
        registering a pending approval (closes the race where a cancel
        arrives between `submit_approval` returning `no_pending` and
        `register_pending_approval` running).
        """
        self._cancellation_requested = True
        if self._inner_runner is not None:
            self._inner_runner.request_cancellation()
            return
        # Wake any parked approval (no-op if none registered yet). An
        # empty `approved_urls` triggers the "no URLs survived approval"
        # branch in `run_description_mission`, emitting one terminal
        # `done(cancelled)` cleanly.
        submit_approval(self.mission.id, approved_urls=[], skip_approval=False)

    def cancel_task(self, task_id: UUID) -> None:
        """Forward to the inner runner. No-op before the SCRAPING phase
        — there are no per-task rows yet.
        """
        if self._inner_runner is not None:
            self._inner_runner.cancel_task(task_id)

    def set_inner_runner(self, runner: MissionRunner) -> None:
        """Called by `run_description_mission` once the inner URL-mode
        runner is constructed. After this, per-task and mission cancels
        forward through to the inner runner's checkpoints rather than
        wake-the-approval-gate.
        """
        self._inner_runner = runner

    @property
    def cancellation_requested(self) -> bool:
        return self._cancellation_requested

    async def run(self) -> None:
        await run_description_mission(
            user=self.user,
            mission=self.mission,
            query=self.query,
            approval_timeout_s=self.approval_timeout_s,
            wrapper=self,
        )


async def run_description_mission(
    *,
    user: CurrentUser,
    mission: Mission,
    query: str,
    approval_timeout_s: float = _DEFAULT_APPROVAL_TIMEOUT_S,
    wrapper: DescriptionMissionRunner | None = None,
) -> None:
    """Run a description-mode mission end-to-end.

    Phases (each row write precedes its emit so invariant 7 holds):
      1. `DISCOVERING` — call the discovery agent; emit per-result
         `url_discovered` events from the tool body.
      2. `AWAITING_APPROVAL` (skipped when `skip_approval=true`) — emit
         `discovery_complete`, register a `_PendingApproval`, park.
      3. `SCRAPING` — construct N task rows, hand to a `MissionRunner`,
         which emits `task_start`/`task_end`/`done`.
      4. `DONE` — set by `MissionRunner.run()` after the rolled-up
         `done` event lands.

    The whole body is wrapped in `try/except/finally` so a programming
    error in any phase still emits a terminal `done`/`error` (invariant
    5 at the mission level).
    """
    _current_user.set(user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    chain = LLMProviderChain(
        primary=OpenRouterProvider(),
        fallback=GroqProvider(),
    )

    trace = start_mission_trace(
        mission_id=mission.id,
        user_id=user.user_id,
        prompt=query,
    )

    terminal_emitted = False

    async def _emit_error(code: str, message: str) -> None:
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "error",
                    "content": {"code": code, "message": message},
                    "mission_id": str(mission.id),
                    "seq": 0,
                }
            )
        )

    async def _emit_done(status: Status) -> None:
        nonlocal terminal_emitted
        await emit_mission_terminal(emitter, mission_id=mission.id, status=status)
        terminal_emitted = True

    try:
        await missions_repo.update_status(mission.id, Status.RUNNING)
        await missions_repo.set_phase(mission.id, MissionPhase.DISCOVERING)

        # --- discovery -------------------------------------------------
        agent = build_discovery_agent()
        deps = DiscoveryDeps(user_id=user.user_id, mission_id=mission.id)

        async def _run(model: Any) -> Any:
            return await agent.run(query, model=model, deps=deps)

        try:
            result = await chain.with_fallback(_run)
        except Exception as exc:
            log.exception("discovery.chain_failed", mission_id=str(mission.id))
            await missions_repo.update_status(mission.id, Status.FAILED)
            await _emit_error("discovery_failed", str(exc))
            await _emit_done(Status.FAILED)
            trace.update(output={"status": "failed", "phase": "discovering"})
            return

        discovery: DiscoveryMissionResult = result.output
        if discovery.status == "error":
            await missions_repo.update_status(mission.id, Status.FAILED)
            await _emit_error(
                discovery.error_code or "discovery_failed",
                discovery.error_message or "discovery failed",
            )
            await _emit_done(Status.FAILED)
            trace.update(output={"status": "failed", "phase": "discovering"})
            return

        # --- persist + emit discovery_complete -------------------------
        await missions_repo.set_discovered_urls(
            mission.id, [u.model_dump() for u in discovery.urls]
        )

        fresh = await missions_repo.get(mission.id)
        awaiting = not (fresh and fresh.skip_approval)

        if awaiting:
            await missions_repo.set_phase(mission.id, MissionPhase.AWAITING_APPROVAL)

        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "discovery_complete",
                    "content": {
                        "count": len(discovery.urls),
                        "awaiting_approval": awaiting,
                    },
                    "mission_id": str(mission.id),
                    "seq": 0,
                }
            )
        )

        # --- approval gate (or skip) ----------------------------------
        approved_urls: list[str]
        if awaiting:
            register_pending_approval(mission.id)
            # Spec 14: a cancel that arrived between the wrapper's
            # `submit_approval(no_pending)` and `register_pending_approval`
            # would be lost without this re-check. Submitting an empty
            # URL list after registration drops cleanly into the
            # "no URLs survived approval" terminal branch below.
            if wrapper is not None and wrapper.cancellation_requested:
                submit_approval(mission.id, approved_urls=[], skip_approval=False)
            approval = await wait_for_approval(mission.id, timeout_s=approval_timeout_s)
            if approval is None or approval.approved_urls is None:
                await missions_repo.update_status(mission.id, Status.CANCELLED)
                await _emit_done(Status.CANCELLED)
                trace.update(output={"status": "cancelled", "phase": "awaiting_approval"})
                return
            approved_urls = approval.approved_urls
            if approval.skip_approval_persisted:
                await missions_repo.set_skip_approval(mission.id, True)
            await missions_repo.set_approved_urls(mission.id, approved_urls)
        else:
            approved_urls = [u.url for u in discovery.urls]
            await missions_repo.set_approved_urls(mission.id, approved_urls)

        if not approved_urls:
            # No URLs survived approval — treat as cancelled (no work to do).
            await missions_repo.update_status(mission.id, Status.CANCELLED)
            await _emit_done(Status.CANCELLED)
            trace.update(output={"status": "cancelled", "phase": "awaiting_approval"})
            return

        # --- scraping --------------------------------------------------
        await missions_repo.set_phase(mission.id, MissionPhase.SCRAPING)
        # Re-read so the inner runner observes the updated phase/approved_urls;
        # the in-memory `mission` instance was created before discovery wrote.
        latest = await missions_repo.get(mission.id)
        runner_mission = latest if latest is not None else mission

        task_rows: list[Task] = []
        for url in approved_urls:
            row = await tasks_repo.create(
                mission_id=mission.id,
                url=url,
                tier_used=Tier.HTTP,
            )
            task_rows.append(row)

        runner = MissionRunner(user=user, mission=runner_mission, tasks=task_rows)
        # Spec 14: register the inner runner with the wrapper so cancel
        # endpoints route through to its `request_cancellation` /
        # `cancel_task` checkpoints once SCRAPING begins.
        if wrapper is not None:
            wrapper.set_inner_runner(runner)
        await runner.run()
        # MissionRunner.run() emits the mission-level `done` and writes
        # `phase=DONE`; mark terminal_emitted so the finally block doesn't
        # double-emit.
        terminal_emitted = True
    except asyncio.CancelledError:
        # Re-raise after a terminal emit so the lifespan TaskGroup can
        # propagate. `_shielded_run` (sse.py) catches the surrounding
        # exception group and logs.
        if not terminal_emitted:
            try:
                await missions_repo.update_status(mission.id, Status.CANCELLED)
                await _emit_done(Status.CANCELLED)
            except Exception:  # pragma: no cover — terminal-emit must not raise
                log.exception(
                    "description.terminal_emit_after_cancel_failed",
                    mission_id=str(mission.id),
                )
        raise
    except Exception as exc:
        log.exception("description.runner_unhandled", mission_id=str(mission.id))
        if not terminal_emitted:
            try:
                await missions_repo.update_status(mission.id, Status.FAILED)
                await _emit_error("agent_failed", str(exc))
                await _emit_done(Status.FAILED)
            except Exception:  # pragma: no cover
                log.exception(
                    "description.terminal_emit_after_error_failed",
                    mission_id=str(mission.id),
                )
    finally:
        if not terminal_emitted:
            # Defense in depth — invariant 5 at the mission level. If any
            # path above slipped past without emitting a terminal, force
            # one now so the slide-over doesn't hang forever.
            try:
                await missions_repo.update_status(mission.id, Status.FAILED)
                await emit_mission_terminal(emitter, mission_id=mission.id, status=Status.FAILED)
            except Exception:  # pragma: no cover
                log.exception(
                    "description.terminal_emit_in_finally_failed",
                    mission_id=str(mission.id),
                )


async def start_description_mission(
    *,
    user: CurrentUser,
    query: str,
    skip_approval: bool = False,
    approval_timeout_s: float = _DEFAULT_APPROVAL_TIMEOUT_S,
) -> UUID:
    """Persist mission row; hand the description-mode runner off to the
    lifespan-scoped TaskGroup; return mission_id immediately.

    Mirrors `start_url_mission`'s contract — the row is written before
    the runner runs, so the first SSE event has a backing row (invariant 7).
    """
    if not 1 <= len(query) <= 2000:
        raise ValueError("query must contain between 1 and 2000 characters")

    _current_user.set(user)
    missions_repo = MissionRepository()
    mission = await missions_repo.create(
        prompt=query,
        mode=MissionMode.DESCRIPTION,
        skip_approval=skip_approval,
    )

    runner = DescriptionMissionRunner(
        user=user,
        mission=mission,
        query=query,
        approval_timeout_s=approval_timeout_s,
    )
    await emitter.adopt_runner(mission.id, runner)
    return mission.id
