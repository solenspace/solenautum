"""Runner helpers for the multi-tier, multi-task agent.

`last_ok_tool_call` walks the agent's message history in reverse to
find the most recent successful tool result (an `*Ok` model). The
runner uses it to recover `snapshot_key`, `markdown`, `latency_ms`,
and `snapshot_truncated` for the `tasks` row update — without passing
the full markdown / raw HTML through the LLM context.

`compute_mission_status_from_db` reads the freshest task statuses from
Neon after the per-mission TaskGroup exits and rolls them up into one
mission-level `Status`. `emit_mission_terminal` formats and dispatches
the `done` SSE event.

The `dict`-form fallback in `_coerce_ok` is defensive against
Pydantic AI patch-version serialization changes: today
(`pydantic_ai==1.44.0`) `ToolReturnPart.content` holds the original
Pydantic model instance, but the fallback validates a dict shape if a
future patch normalizes content to a JSON dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.persistence.models import Status
from app.tools.dynamic import DynamicScrapeOk
from app.tools.http import HttpScrapeOk
from app.tools.stealth import StealthScrapeOk

if TYPE_CHECKING:
    from app.persistence.repository import TaskRepository
    from app.sse import SseEmitter

OkResult = HttpScrapeOk | StealthScrapeOk | DynamicScrapeOk

_OK_TYPES: tuple[type[BaseModel], ...] = (
    HttpScrapeOk,
    StealthScrapeOk,
    DynamicScrapeOk,
)


def last_ok_tool_call(result: Any) -> OkResult | None:
    """Return the most recent `ToolReturnPart` whose content is an
    `*Ok` model, or `None` if the agent never had a successful tool
    call.

    `result` is the value returned by `Agent.run(...)`; it exposes
    `all_messages()` per Pydantic AI's API.

    Note: if the agent had a partial success (e.g. `scrape_http` ok →
    `scrape_stealth` failure → mission_result.status="error"), this
    returns the HTTP-tier ok. The system prompt forbids this scenario
    ("Call exactly one tool successfully per mission. After ok, do not
    call more tools."); the runner's caller should treat the recovered
    snapshot as advisory when `mission_result.status == "error"`.
    """
    for message in reversed(result.all_messages()):
        if not isinstance(message, ModelRequest):
            continue
        for part in reversed(message.parts):
            if not isinstance(part, ToolReturnPart):
                continue
            ok = _coerce_ok(part.content)
            if ok is not None:
                return ok
    return None


def _coerce_ok(content: Any) -> OkResult | None:
    if isinstance(content, _OK_TYPES):
        return content  # type: ignore[return-value]
    if isinstance(content, dict) and content.get("status") == "ok":
        for cls in _OK_TYPES:
            try:
                return cls.model_validate(content)  # type: ignore[return-value]
            except ValidationError:
                continue
    return None


async def compute_mission_status_from_db(mission_id: UUID, tasks_repo: TaskRepository) -> Status:
    """Roll the per-task statuses up into one mission-level status.

    - SUCCEEDED iff every task succeeded.
    - FAILED if any task failed (FAILED dominates CANCELLED so a
      partially-cancelled-but-also-failed mission surfaces as failed —
      the actionable signal).
    - CANCELLED otherwise (any task cancelled, none failed). Includes
      the empty-tasks edge case, which the validator in
      `start_url_mission` already prevents but is handled defensively.

    Reads from the DB so it observes the freshest status set by each
    `_run_task` coroutine; the in-memory `Task` instances captured at
    creation time are stale by the time the TaskGroup exits.
    """
    tasks = await tasks_repo.list_by_mission(mission_id)
    statuses = {t.status for t in tasks}
    if statuses == {Status.SUCCEEDED}:
        return Status.SUCCEEDED
    if Status.FAILED in statuses:
        return Status.FAILED
    return Status.CANCELLED


async def emit_mission_terminal(
    emitter: SseEmitter,
    *,
    mission_id: UUID,
    status: Status,
    cost_cents: int = 0,
) -> None:
    """Emit the mission-level `done` SSE event with the rolled-up status.

    The schema's `mission_status` enum is succeeded/failed/cancelled;
    PENDING/RUNNING are filtered upstream (`compute_mission_status_from_db`
    only returns terminal values).
    """
    from autumn_sse_protocol import SseEvent

    mission_status = _MISSION_STATUS_MAP[status]
    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": "done",
                "content": {
                    "mission_status": mission_status,
                    "cost_cents": cost_cents,
                },
                "mission_id": str(mission_id),
                "seq": 0,
            }
        )
    )


_MISSION_STATUS_MAP: dict[Status, str] = {
    Status.SUCCEEDED: "succeeded",
    Status.FAILED: "failed",
    Status.CANCELLED: "cancelled",
}


_TASK_STATUS_MAP: dict[Status, str] = {
    Status.SUCCEEDED: "succeeded",
    Status.FAILED: "failed",
    Status.CANCELLED: "cancelled",
}


async def emit_task_terminal(
    emitter: SseEmitter,
    *,
    mission_id: UUID,
    task_id: UUID,
    status: Status,
    content_extras: dict[str, Any] | None = None,
) -> None:
    """Emit a `task_end` SSE event for one task.

    Centralizes the schema-shape so the runner's per-task path and the
    rare-edge cancel-route path produce identical events. `content_extras`
    optionally carries `preview` / `snapshot_key` / `latency_ms` for the
    success path; the cancel paths pass nothing.
    """
    from autumn_sse_protocol import SseEvent

    content: dict[str, Any] = {"status": _TASK_STATUS_MAP[status]}
    if content_extras:
        content.update(content_extras)
    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": "task_end",
                "content": content,
                "mission_id": str(mission_id),
                "task_id": str(task_id),
                "seq": 0,
            }
        )
    )
