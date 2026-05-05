from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.agent import build_agent
from app.llm import GroqProvider, LLMProviderChain, OpenRouterProvider
from app.observability import start_mission_trace
from app.persistence.models import MissionMode, Status, Tier
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
    helper keeps the four call sites below from drifting on the placeholder
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


async def run_url_mission(*, user: CurrentUser, url: str) -> UUID:
    """Create the mission row, run a single HTTP-tier task, emit SSE.

    Enforces:
      - invariant 1 — `assert_safe_url` before any DB write
      - invariant 7 — mission/task rows persist before any SSE event
      - invariant 5 — every code path emits a terminal event for the task
        AND a mission-level `done`. The success block is wrapped in the
        same `try/except` that owns the failure terminals so a transient
        DB error inside the post-agent path can't leave the stream open.
      - invariant 10 — only an authenticated user reaches the tool (the
        contextvar binds at request entry; mission status is set to RUNNING
        before the agent loop, and Spec 07 has no cancellation path that
        can flip it)
      - invariant 12 — provider switch only on 429/5xx, owned by `LLMProviderChain`
    """
    assert_safe_url(url)

    _current_user.set(user)
    missions = MissionRepository()
    tasks = TaskRepository()

    mission = await missions.create(prompt=url, mode=MissionMode.URL)
    await missions.update_status(mission.id, Status.RUNNING)

    task = await tasks.create(mission_id=mission.id, url=url, tier_used=Tier.HTTP)
    await tasks.update(task.id, status=Status.RUNNING)

    trace = start_mission_trace(
        mission_id=mission.id,
        task_id=task.id,
        user_id=user.user_id,
        prompt=url,
    )

    await _emit(
        "task_start",
        {"url": url, "tier": SseTier.http.value},
        mission_id=mission.id,
        task_id=task.id,
    )

    chain = LLMProviderChain(primary=OpenRouterProvider(), fallback=GroqProvider())
    deps = HttpToolDeps(robots_override=mission.robots_override)
    agent, last_scrape = build_agent()

    try:

        async def _run(model):  # type: ignore[no-untyped-def]
            # Reset the closure on every attempt so a fallback retry after a
            # partial primary run doesn't merge two tool histories.
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

    return mission.id
