"""Tavily-backed `SearchProvider`. Hits `https://api.tavily.com/search`
with `search_depth="basic"`, `include_answer=False`, `max_results=20`.

Per-mission cost cap is enforced at three layers (see Spec 12):
  1. `discover_urls` agent system prompt constrains exactly one call.
  2. `app/tools/discover.py` rejects a second call within the same mission.
  3. The `max_results` kwarg here caps at 20 server-side too.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.config import settings
from app.search import DiscoveredUrl


class _TavilyResult(BaseModel):
    url: str
    title: str | None = None
    score: float
    raw_favicon: str | None = None


class TavilyProvider:
    name = "tavily"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search(self, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        if settings.tavily_api_key is None:
            raise RuntimeError("TAVILY_API_KEY is not configured")

        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": min(max_results, 20),
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if owned_client:
                await client.aclose()

        results = [_TavilyResult.model_validate(r) for r in data.get("results", [])]
        return [
            DiscoveredUrl(
                url=r.url,
                score=max(0.0, min(1.0, r.score)),
                source="tavily",
                favicon_url=r.raw_favicon,
                title=r.title,
            )
            for r in results
        ]
