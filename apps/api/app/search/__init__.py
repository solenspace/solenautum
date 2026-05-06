"""Search providers for description-mode mission URL discovery.

The `SearchProvider` Protocol decouples the discovery agent from any
specific vendor; `TavilyProvider` is the only implementation today, but
Exa or Brave can swap in by binding a different class to the agent. The
per-mission cost cap (max 1 search, max 20 results) is enforced upstream
in `app/tools/discover.py` and reaffirmed here via the `max_results` kwarg
upper bound.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class DiscoveredUrl(BaseModel):
    """One search result returned by a SearchProvider.

    Schema matches the persisted shape in `missions.discovered_urls` jsonb.
    """

    url: str
    score: float = Field(..., ge=0.0, le=1.0)
    source: str
    favicon_url: str | None = None
    title: str | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]: ...


__all__ = ["DiscoveredUrl", "SearchProvider"]
