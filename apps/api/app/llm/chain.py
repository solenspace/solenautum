from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

import httpx
import structlog
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

from app.observability import emit_provider_switch

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from app.llm.base import LLMProvider


T = TypeVar("T")

log = structlog.get_logger()


def _status_code(exc: BaseException) -> int | None:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _is_provider_fault(status: int | None) -> bool:
    return status is not None and (status == 429 or status >= 500)


def _is_malformed_completion(exc: UnexpectedModelBehavior) -> bool:
    """Return True when an `UnexpectedModelBehavior` indicates the upstream
    returned a structurally invalid ChatCompletion (free-tier OpenRouter
    routinely returns `{"object": null, "id": null, "choices": null}` and
    similar empty-shape responses; those should switch to the fallback
    provider, not surface as a hard mission failure).
    """
    msg = str(exc).lower()
    if "invalid response from" not in msg:
        return False
    return any(
        signature in msg
        for signature in (
            "input_value=none",
            "validation error",
            "literal_error",
            "list_type",
            "string_type",
        )
    )


class LLMProviderChain:
    """Try the primary provider; on rate-limit (429), upstream 5xx, OR a
    structurally malformed ChatCompletion (free-tier OpenRouter), switch
    to the fallback exactly once. Tool-arg / pydantic / business errors
    that originate inside the agent's own validation propagate
    immediately — invariant 12 still holds for those.
    """

    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def with_fallback(self, run: Callable[[Model], Awaitable[T]]) -> T:
        try:
            return await run(self._primary.model())
        except (ModelHTTPError, httpx.HTTPStatusError) as exc:
            status = _status_code(exc)
            if not _is_provider_fault(status):
                raise
            reason = "rate_limit" if status == 429 else "upstream_5xx"
            log.warning(
                "llm.provider.fallback",
                reason=reason,
                status_code=status,
                **{"from": self._primary.name, "to": self._fallback.name},
            )
            emit_provider_switch(
                from_=self._primary.name,
                to=self._fallback.name,
                reason=reason,
            )
            return await run(self._fallback.model())
        except UnexpectedModelBehavior as exc:
            if not _is_malformed_completion(exc):
                raise
            log.warning(
                "llm.provider.fallback",
                reason="malformed_completion",
                **{"from": self._primary.name, "to": self._fallback.name},
            )
            emit_provider_switch(
                from_=self._primary.name,
                to=self._fallback.name,
                reason="malformed_completion",
            )
            return await run(self._fallback.model())
