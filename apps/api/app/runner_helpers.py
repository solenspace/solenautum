"""Runner helpers for the multi-tier agent.

`_last_ok_tool_call` walks the agent's message history in reverse to
find the most recent successful tool result (an `*Ok` model). The
runner uses it to recover `snapshot_key`, `markdown`, `latency_ms`,
and `snapshot_truncated` for the `tasks` row update — without passing
the full markdown / raw HTML through the LLM context.

The `dict`-form fallback in `_coerce_ok` is defensive against
Pydantic AI patch-version serialization changes: today
(`pydantic_ai==1.44.0`) `ToolReturnPart.content` holds the original
Pydantic model instance, but the fallback validates a dict shape if a
future patch normalizes content to a JSON dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.tools.dynamic import DynamicScrapeOk
from app.tools.http import HttpScrapeOk
from app.tools.stealth import StealthScrapeOk

OkResult = HttpScrapeOk | StealthScrapeOk | DynamicScrapeOk

_OK_TYPES: tuple[type[BaseModel], ...] = (
    HttpScrapeOk,
    StealthScrapeOk,
    DynamicScrapeOk,
)


def _last_ok_tool_call(result: Any) -> OkResult | None:
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
