"""URL discovery tool for description-mode missions.

The agent calls `discover_urls` exactly once per mission run; this module
enforces that contract in three ways:
  1. The agent's system prompt instructs the model to call once.
  2. The contextvar-scoped `_discovery_called` set rejects a second call
     within the same async context.
  3. The Tavily provider caps `max_results` at 20 server-side.

After Tavily returns, every URL is funneled through `assert_safe_url`
(defense-in-depth — Spec 12 only mandates SSRF at `/approve` time, but a
poisoned search response can otherwise render unsafe URLs in the UI).
URLs that fail the SSRF check are silently dropped.

Per-URL `url_discovered` SSE events fire as the filtered results arrive,
so the slide-over can render a streaming list.
"""

from __future__ import annotations

import contextvars
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.observability import observe
from app.search import DiscoveredUrl
from app.search.tavily import TavilyProvider
from app.security import UrlNotAllowed, assert_safe_url
from app.sse import emitter
from autumn_sse_protocol import SseEvent


class DiscoverArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    max_results: int = Field(default=20, ge=1, le=20)


class DiscoveryOk(BaseModel):
    status: Literal["ok"] = "ok"
    urls: list[DiscoveredUrl]


class DiscoveryFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal["rate_limited", "upstream_error", "no_results"]
    detail: str | None = None


DiscoveryResult = DiscoveryOk | DiscoveryFailure


class DiscoverDeps(BaseModel):
    user_id: str
    mission_id: UUID


_discovery_called: contextvars.ContextVar[frozenset[UUID]] = contextvars.ContextVar(
    "discovery_called", default=frozenset()
)


@observe(name="tool.discover_urls")  # type: ignore[untyped-decorator]
async def discover_urls(deps: DiscoverDeps, args: DiscoverArgs) -> DiscoveryResult:
    """Tavily-backed search. Per-mission single-call cap is enforced
    in-process; the agent's system prompt also constrains it.

    Defense-in-depth: each Tavily-supplied URL is run through
    `assert_safe_url` before it is emitted as an SSE event or returned.
    """
    called = _discovery_called.get()
    if deps.mission_id in called:
        return DiscoveryFailure(
            reason="upstream_error",
            detail="discovery already called this mission",
        )
    _discovery_called.set(called | {deps.mission_id})

    provider = TavilyProvider()
    try:
        urls = await provider.search(args.query, max_results=args.max_results)
    except Exception as exc:
        return DiscoveryFailure(reason="upstream_error", detail=str(exc))

    safe_urls: list[DiscoveredUrl] = []
    for u in urls:
        try:
            assert_safe_url(u.url)
        except UrlNotAllowed:
            # Tavily can return junk (private-IP literals, unsupported schemes)
            # — drop without raising so one bad URL doesn't tank the mission.
            continue
        safe_urls.append(u)

    if not safe_urls:
        return DiscoveryFailure(reason="no_results")

    for u in safe_urls:
        await emitter.emit(
            SseEvent.model_validate(
                {
                    "type": "url_discovered",
                    "content": {
                        "url": u.url,
                        "source": u.source,
                        "score": u.score,
                    },
                    "mission_id": str(deps.mission_id),
                    "seq": 0,  # emitter assigns
                }
            )
        )

    return DiscoveryOk(urls=safe_urls)
