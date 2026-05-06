from __future__ import annotations

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


__all__ = ["emit_provider_switch", "observe", "start_mission_trace"]
