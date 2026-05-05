from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

import httpx
from pydantic_ai.exceptions import ModelHTTPError

from app.observability import emit_provider_switch

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from app.llm.base import LLMProvider


T = TypeVar("T")

log = logging.getLogger(__name__)


def _status_code(exc: BaseException) -> int | None:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _is_provider_fault(status: int | None) -> bool:
    return status is not None and (status == 429 or status >= 500)


class LLMProviderChain:
    """Try the primary provider; on rate-limit (429) or upstream 5xx, switch to the
    fallback exactly once. Tool-arg / pydantic / business errors propagate
    immediately — invariant 12.
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
                extra={
                    "from": self._primary.name,
                    "to": self._fallback.name,
                    "reason": reason,
                    "status_code": status,
                },
            )
            emit_provider_switch(
                from_=self._primary.name,
                to=self._fallback.name,
                reason=reason,
            )
            return await run(self._fallback.model())
