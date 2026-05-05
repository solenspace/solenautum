from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from app.agent import build_agent
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import start_mission_trace
from app.persistence.models import Mission, MissionMode, Status, Task, Tier
from app.persistence.repository import MissionRepository, TaskRepository
from app.security import CurrentUser, _current_user, assert_safe_url
from app.sse import emitter
from app.tools.http import HttpToolDeps
from autumn_sse_protocol import SseEvent
from autumn_sse_protocol.models import (
    MissionStatus as SseMissionStatus,
    Status as SseStatus,
    Tier as SseTier,
)

log = logging.getLogger(__name__)

_PREVIEW_CHARS = 500

# Strong references to detached agent tasks. asyncio.create_task only weakly
# references its task via the running loop, so a long-running detached
# coroutine can be garbage-collected mid-flight if no caller holds it. The set
# + add_done_callback pair fixes that lifetime hazard. Spec 10 replaces
# `_spawn_detached` with TaskGroup.create_task and the call sites do not change.
_inflight_tasks: set[asyncio.Task[None]] = set()


async def _emit(
    type_: str,
    content: dict[str, Any],
    *,
    mission_id: UUID,
    task_id: UUID | None = None,
) -> None:
    """Build, validate, and emit one SSE event.

    `seq=0` is a placeholder — `SseEmitter.emit` overwrites it under its lock
    with the next monotonic value (invariant 4). Centralizing this in one
    helper keeps every call site below from drifting on the placeholder
    convention.
    """
    payload: dict[str, Any] = {
        "type": type_,
        "content": content,
        "mission_id": str(mission_id),
        "seq": 0,
    }
    if task_id is not None:
        payload["task_id"] = str(task_id)
    await emitter.emit(SseEvent.model_validate(payload))


def _spawn_detached(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    """Spawn a fire-and-forget coroutine and hold a strong reference until done.

    TODO(spec-10): replace with TaskGroup.create_task. The current shape
    deviates from invariant 3 (TaskGroup ownership) because the spawned task
    outlives the request scope of the caller. Spec 08 accepts the deviation;
    Spec 10 closes it when the runner adopts structured concurrency for
    multi-task missions.
    """
    task = asyncio.create_task(coro)
    _inflight_tasks.add(task)
    task.add_done_callback(_inflight_tasks.discard)
    return task


async def _create_mission_and_task(*, user: CurrentUser, url: str) -> tuple[Mission, Task]:
    """SSRF guard, persist mission/task rows, emit task_start.

    Enforces:
      - invariant 1 — `assert_safe_url` fires before any DB write
      - invariant 7 — mission/task rows persist before any SSE event
      - invariant 10 — `_current_user` binds before any repository call
    """
    assert_safe_url(url)

    _current_user.set(user)
    missions = MissionRepository()
    tasks = TaskRepository()

    mission = await missions.create(prompt=url, mode=MissionMode.URL)
    await missions.update_status(mission.id, Status.RUNNING)

    task = await tasks.create(mission_id=mission.id, url=url, tier_used=Tier.HTTP)
    await tasks.update(task.id, status=Status.RUNNING)

    await _emit(
        "task_start",
        {"url": url, "tier": SseTier.http.value},
        mission_id=mission.id,
        task_id=task.id,
    )

    return mission, task


async def _execute_url_mission(
    *,
    user: CurrentUser,
    mission: Mission,
    task: Task,
    url: str,
) -> None:
    """Run the agent loop and emit terminal events for one (mission, task).

    Enforces:
      - invariant 5 — every code path emits a task-level terminal AND a
        mission-level `done`. The success and failure branches share one
        try/except so a transient DB error after the agent run still closes
        the stream cleanly.
      - invariant 12 — provider switch only on 429/5xx, owned by
        `LLMProviderChain`.

    Re-binds `_current_user` defensively. Python 3.11+ copies the calling
    context into `asyncio.create_task`, but binding here keeps the function
    correct even if a future caller invokes it without setting the contextvar
    first.
    """
    _current_user.set(user)
    missions = MissionRepository()
    tasks = TaskRepository()

    trace = start_mission_trace(
        mission_id=mission.id,
        task_id=task.id,
        user_id=user.user_id,
        prompt=url,
    )

    chain = LLMProviderChain(primary=OpenRouterProvider(), fallback=GroqProvider())
    deps = HttpToolDeps(robots_override=mission.robots_override)
    agent, last_scrape = build_agent()

    try:

        async def _run(model):  # type: ignore[no-untyped-def]
            # Reset on every attempt so a fallback retry after a partial primary
            # run doesn't merge two tool histories.
            last_scrape.clear()
            return await agent.run(url, model=model, deps=deps)

        result = await chain.with_fallback(_run)

        full_markdown = last_scrape[-1].markdown if last_scrape else ""
        latency_ms = last_scrape[-1].latency_ms if last_scrape else None
        preview = full_markdown[:_PREVIEW_CHARS]

        await tasks.update(
            task.id,
            status=Status.SUCCEEDED,
            latency_ms=latency_ms,
            parsed_markdown=full_markdown,
            snapshot_truncated=False,
        )

        task_end_content: dict[str, Any] = {
            "status": SseStatus.succeeded.value,
            "preview": preview,
        }
        if latency_ms is not None:
            task_end_content["latency_ms"] = latency_ms
        await _emit(
            "task_end",
            task_end_content,
            mission_id=mission.id,
            task_id=task.id,
        )

        await missions.update_status(mission.id, Status.SUCCEEDED)
        await _emit(
            "done",
            {"mission_status": SseMissionStatus.succeeded.value, "cost_cents": 0},
            mission_id=mission.id,
        )

        trace.update(
            output={
                "status": "succeeded",
                "summary": result.output.summary,
                "primary_url": result.output.primary_url,
            },
        )
    except Exception as exc:
        log.exception(
            "mission.failed",
            extra={"mission_id": str(mission.id), "task_id": str(task.id)},
        )
        await tasks.update(task.id, status=Status.FAILED)
        await missions.update_status(mission.id, Status.FAILED)
        await _emit(
            "error",
            {"code": "agent_failed", "message": str(exc)},
            mission_id=mission.id,
            task_id=task.id,
        )
        await _emit(
            "done",
            {"mission_status": SseMissionStatus.failed.value, "cost_cents": 0},
            mission_id=mission.id,
        )
        trace.update(output={"status": "failed"})


async def start_url_mission(*, user: CurrentUser, url: str) -> UUID:
    """Persist rows, emit `task_start`, spawn the agent loop, return the
    mission id. The caller (POST /missions) can hand the id to a separate
    SSE consumer that re-attaches via `emitter.stream(mission_id)`.
    """
    mission, task = await _create_mission_and_task(user=user, url=url)
    _spawn_detached(
        _execute_url_mission(user=user, mission=mission, task=task, url=url),
    )
    return mission.id


async def run_url_mission(*, user: CurrentUser, url: str) -> UUID:
    """Inline runner used by the legacy `GET /run-mission?url=...` route.

    Blocks until the agent loop terminates so the route's `StreamingResponse`
    can replay the full event sequence from the ring buffer in one shot. Spec
    10 retires this in favor of structured TaskGroup ownership; for now it
    shares its body with `start_url_mission` via the helpers above.
    """
    mission, task = await _create_mission_and_task(user=user, url=url)
    await _execute_url_mission(user=user, mission=mission, task=task, url=url)
    return mission.id
