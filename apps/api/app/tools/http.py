from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel, Field
from scrapling.fetchers import AsyncFetcher

from app.extract import MarkdownExtractor
from app.observability import observe
from app.security import assert_robots_allows, assert_safe_url


class HttpScrapeArgs(BaseModel):
    """Tool input. The Pydantic AI agent fills this from its tool call."""

    url: str = Field(..., max_length=2048)


class HttpScrapeResult(BaseModel):
    """Tool output. Returned to the agent and captured by the runner via the
    closure registered in `app.agent.build_agent`.
    """

    url: str
    markdown: str
    raw_html: bytes
    latency_ms: int


@dataclass(frozen=True, slots=True)
class HttpToolDeps:
    """Mission-scoped dependencies passed via Pydantic AI's `RunContext`."""

    robots_override: bool


@observe(name="tool.scrape_http")  # type: ignore[untyped-decorator]
async def scrape_http(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeResult:
    """Fetch a URL via Scrapling's `AsyncFetcher` and pipe the bytes through
    Crawl4AI for markdown extraction. Honors invariants 1, 6, 11.
    """
    assert_safe_url(args.url)  # invariant 1 — SSRF guard before any egress
    await assert_robots_allows(  # invariant 11 — robots.txt unless overridden
        args.url, robots_override=deps.robots_override
    )

    start = perf_counter()
    page = await AsyncFetcher.get(
        args.url,
        stealthy_headers=True,
        follow_redirects=True,
        timeout=15,
    )
    if page.status >= 400:
        raise RuntimeError(f"upstream returned HTTP {page.status} for {args.url}")

    extracted = await MarkdownExtractor().extract(html=str(page.body), source_url=str(page.url))
    latency_ms = int((perf_counter() - start) * 1000)

    return HttpScrapeResult(
        url=str(page.url),
        markdown=extracted.markdown,
        raw_html=extracted.raw_html,
        latency_ms=latency_ms,
    )
