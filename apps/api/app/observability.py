from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langfuse import Langfuse
from langfuse.decorators import langfuse_context, observe

from app.config import settings

if TYPE_CHECKING:
    from langfuse.client import StatefulTraceClient

log = logging.getLogger(__name__)


def _build_client() -> Langfuse:  # type: ignore[no-any-unimported]
    """Build the singleton Langfuse client. When credentials are missing the
    SDK is disabled — `.trace()` and span methods become no-ops, so callers do
    not need to branch on configuration.
    """
    enabled = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
        enabled=enabled,
    )


_client = _build_client()


def start_mission_trace(  # type: ignore[no-any-unimported]
    *,
    mission_id: UUID,
    user_id: str,
    prompt: str,
    task_id: UUID | None = None,
) -> StatefulTraceClient:
    """Open one Langfuse trace per mission. `mission_id` and (optionally)
    `task_id` land on the trace metadata (per `code-standards.md`
    observability rule) so a Langfuse search by either id surfaces the
    full execution. Tools attach as nested spans via the `@observe()`
    decorator; the runner calls `.update(output=...)` on the returned
    handle when the mission terminates.

    Multi-task missions (Spec 10) leave `task_id` unset at the trace
    level — per-task spans inherit the trace and carry their own
    `task_id` via `@observe`-decorated tool calls.
    """
    metadata: dict[str, Any] = {
        "mission_id": str(mission_id),
        "user_id": user_id,
    }
    if task_id is not None:
        metadata["task_id"] = str(task_id)
    return _client.trace(
        name="mission",
        id=str(mission_id),
        user_id=user_id,
        input=prompt,
        metadata=metadata,
    )


_COST_FETCH_TIMEOUT_S = 5.0


async def fetch_mission_cost_cents(mission_id: UUID) -> int | None:
    """Query Langfuse for the trace's rolled-up cost in USD cents.

    Returns `None` if the trace is missing, the API is unreachable, the
    request times out, or the SDK is disabled (no credentials). The
    runner treats `None` as "cost unavailable" and writes `0` to
    `missions.cost_cents` — the sidebar then renders `?` for terminal
    missions with zero cost.

    The SDK's `fetch_trace` is sync; `asyncio.to_thread` keeps the event
    loop free during the network round-trip. The 5s `wait_for` deadline
    bounds the worst case so a hung Langfuse cannot pin the mission's
    `done` event for the SDK's default 60s socket timeout. No retry loop
    here — a single 5xx must not become a runaway billing event
    (`llm-cost-guard` invariant).
    """
    try:
        trace = await asyncio.wait_for(
            asyncio.to_thread(_client.fetch_trace, str(mission_id)),
            timeout=_COST_FETCH_TIMEOUT_S,
        )
    except Exception:
        log.exception(
            "langfuse.fetch_trace_failed",
            extra={"mission_id": str(mission_id)},
        )
        return None

    cost_usd = getattr(getattr(trace, "data", None), "totalCost", None) or 0.0
    return round(float(cost_usd) * 100)


def emit_provider_switch(*, from_: str, to: str, reason: str) -> None:
    """Tag the active Langfuse observation with `provider_switch` metadata so
    a 429/5xx-triggered fallback (invariant 12) is visible in the trace tree.
    """
    metadata: dict[str, Any] = {
        "provider_switch": {"from": from_, "to": to, "reason": reason},
    }
    try:
        langfuse_context.update_current_observation(metadata=metadata)
    except Exception as exc:  # pragma: no cover — observability must never raise
        log.warning(
            "langfuse.update_current_observation_failed",
            extra={"error": str(exc), "from": from_, "to": to, "reason": reason},
        )


__all__ = [
    "emit_provider_switch",
    "fetch_mission_cost_cents",
    "observe",
    "start_mission_trace",
]
