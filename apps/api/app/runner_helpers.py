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
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
)

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

    Partial-success semantics:
    - SUCCEEDED if at least one task succeeded. Description-mode missions
      routinely fan out to 10-20 Tavily URLs, a handful of which return
      403/Cloudflare-blocked. Calling the whole mission FAILED in that
      case misleads the user — most of the requested work landed and is
      visible in the UI. The aside surfaces per-task failures with a red
      dot + count, so the actionable signal isn't lost.
    - CANCELLED if every non-cancelled task was cancelled (i.e. user-
      initiated abort on a mission that produced no successes).
    - FAILED otherwise (no successes, no cancels — every task hit a
      hard failure).

    Reads from the DB so it observes the freshest status set by each
    `_run_task` coroutine; the in-memory `Task` instances captured at
    creation time are stale by the time the TaskGroup exits.
    """
    tasks = await tasks_repo.list_by_mission(mission_id)
    statuses = {t.status for t in tasks}
    if Status.SUCCEEDED in statuses:
        return Status.SUCCEEDED
    if statuses and statuses <= {Status.CANCELLED}:
        return Status.CANCELLED
    return Status.FAILED


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


# Per-tool latency cap for the synthesized `tool_end` event when the
# real measurement is missing (Pydantic AI does not record timestamps
# on `ToolCallPart` / `ToolReturnPart`). The cap keeps the figure
# advisory rather than misleading.
_TOOL_LATENCY_FALLBACK_MS = 0


async def emit_agent_observability(
    emitter: SseEmitter,
    *,
    mission_id: UUID,
    task_id: UUID,
    result: Any,
) -> None:
    """Walk the agent's message history and emit synthesized `token`,
    `tool_start`, and `tool_end` events for everything that happened
    inside the agent loop.

    Pydantic AI's `agent.run(...)` returns a one-shot result; the
    intermediate state (model reasoning text, tool calls, tool returns)
    is recoverable only via `result.all_messages()`. We replay it onto
    the SSE channel so the slide-over's lane log shows what the agent
    actually did instead of jumping straight from `task_start` to
    `task_end`.

    Live token streaming would require switching to `agent.iter()` with
    delta forwarding — that is a larger rewrite of `_run_task`. The
    post-walk approach here gives the user the same content (reasoning
    + tool chips) at the cost of one extra SSE batch per task.

    Emit order is the original message order so the UI's lane log reads
    as a chronological transcript.
    """

    messages = _safe_all_messages(result)
    if not messages:
        return

    # Pair each `ToolCallPart` with its later `ToolReturnPart` so we
    # can emit a single synthetic `tool_end` per call carrying the
    # success summary.
    pending_tools: dict[str, dict[str, Any]] = {}

    for message in messages:
        if isinstance(message, ModelResponse):
            for response_part in message.parts:
                if (isinstance(response_part, ThinkingPart) and response_part.content) or (
                    isinstance(response_part, TextPart) and response_part.has_content()
                ):
                    await _emit_event(
                        emitter,
                        mission_id=mission_id,
                        task_id=task_id,
                        type_="token",
                        content=response_part.content,
                    )
                elif isinstance(response_part, ToolCallPart):
                    tool_call_id = response_part.tool_call_id or response_part.tool_name
                    args = _coerce_tool_args(response_part)
                    pending_tools[tool_call_id] = {
                        "tool_name": response_part.tool_name,
                        "args": args,
                    }
                    await _emit_event(
                        emitter,
                        mission_id=mission_id,
                        task_id=task_id,
                        type_="tool_start",
                        content={"tool_name": response_part.tool_name, "args": args},
                    )
        elif isinstance(message, ModelRequest):
            for request_part in message.parts:
                if not isinstance(request_part, ToolReturnPart):
                    continue
                start = pending_tools.pop(
                    request_part.tool_call_id or request_part.tool_name,
                    {"tool_name": request_part.tool_name, "args": {}},
                )
                ok = _coerce_ok(request_part.content) is not None
                summary = _tool_return_summary(request_part.content)
                await _emit_event(
                    emitter,
                    mission_id=mission_id,
                    task_id=task_id,
                    type_="tool_end",
                    content={
                        "tool_name": start["tool_name"],
                        "duration_ms": _TOOL_LATENCY_FALLBACK_MS,
                        "ok": ok,
                        "summary": summary,
                    },
                )

    # Fire `tool_end` for any tool call whose return never landed
    # (the agent crashed or was cancelled mid-call). The lane log
    # otherwise shows a half-open chip with no resolution.
    for entry in pending_tools.values():
        await _emit_event(
            emitter,
            mission_id=mission_id,
            task_id=task_id,
            type_="tool_end",
            content={
                "tool_name": entry["tool_name"],
                "duration_ms": _TOOL_LATENCY_FALLBACK_MS,
                "ok": False,
                "summary": "no return",
            },
        )


def _safe_all_messages(result: Any) -> list[Any]:
    try:
        return list(result.all_messages())
    except Exception:
        return []


def _coerce_tool_args(part: ToolCallPart) -> dict[str, Any]:
    args = part.args
    if isinstance(args, dict):
        return {k: _shorten(v) for k, v in args.items()}
    if isinstance(args, str):
        # Pydantic AI passes the raw model JSON for tool args when the
        # model emits a single string. Surfacing that verbatim is
        # noisier than helpful in the UI; truncate.
        return {"raw": _shorten(args)}
    return {}


def _shorten(value: Any, *, max_chars: int = 80) -> Any:
    """Trim a long string-or-stringified value to keep the tool-call
    chip on one line. Non-string values pass through unchanged.
    """
    if isinstance(value, str):
        if len(value) > max_chars:
            return f"{value[: max_chars - 1]}…"
        return value
    return value


def _tool_return_summary(content: Any) -> str | None:
    if isinstance(content, BaseModel):
        # Tier-tool return shapes (`HttpScrapeOk` etc.) carry `url` and
        # a status; surface the URL as the human summary so the chip
        # doesn't echo the entire markdown.
        url = getattr(content, "url", None)
        if isinstance(url, str):
            return url
        status = getattr(content, "status", None)
        if isinstance(status, str):
            return status
    if isinstance(content, dict):
        url = content.get("url")
        if isinstance(url, str):
            return url
        return None
    if isinstance(content, str):
        shortened = _shorten(content)
        return shortened if isinstance(shortened, str) else None
    return None


async def _emit_event(
    emitter: SseEmitter,
    *,
    mission_id: UUID,
    task_id: UUID,
    type_: str,
    content: Any,
) -> None:
    from autumn_sse_protocol import SseEvent

    await emitter.emit(
        SseEvent.model_validate(
            {
                "type": type_,
                "content": content,
                "mission_id": str(mission_id),
                "task_id": str(task_id),
                "seq": 0,
            }
        )
    )
