"""HTTP tier — Scrapling `AsyncFetcher` + Crawl4AI markdown extraction.

Returns `HttpScrapeOk | HttpScrapeFailure`. Reasons drive the agent's
escalation contract; see `agent.py`'s system prompt. The fetch acquires
a layered HTTP slot (per-mission then global) so a 20-URL mission does
not saturate the process-wide budget.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from scrapling.fetchers import AsyncFetcher

from app.concurrency import current_mission_semaphores
from app.extract import MarkdownExtractor
from app.observability import observe
from app.persistence.snapshot import persist_snapshot
from app.security import assert_robots_allows, assert_safe_url
from app.tools._waf import TERMINAL_WAFS, body_excerpt, detect_waf

_extractor = MarkdownExtractor()


class HttpScrapeArgs(BaseModel):
    """Tool input. The Pydantic AI agent fills this from its tool call."""

    url: str = Field(..., max_length=2048)


class HttpScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class HttpScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "protected_cloudflare",
        "site_not_supported",
        "javascript_required",
        "upstream_error",
        "not_found",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


HttpScrapeResult = HttpScrapeOk | HttpScrapeFailure


class HttpToolDeps(BaseModel):
    """Mission-scoped dependencies passed via Pydantic AI's `RunContext`.

    `user_id` / `mission_id` / `task_id` thread through to
    `persist_snapshot` so the snapshot key is uniformly scoped.
    """

    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


@observe(name="tool.scrape_http")  # type: ignore[untyped-decorator]
async def scrape_http(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeResult:
    """Fetch a URL via Scrapling's `AsyncFetcher` and pipe the bytes through
    Crawl4AI for markdown extraction. Honors invariants 1, 6, 9, 11.
    """
    assert_safe_url(args.url)  # invariant 1 — SSRF guard before any egress
    await assert_robots_allows(  # invariant 11 — robots.txt unless overridden
        args.url, robots_override=deps.robots_override
    )

    start = perf_counter()
    async with current_mission_semaphores().http_slot():
        page = await AsyncFetcher.get(
            args.url,
            stealthy_headers=True,
            follow_redirects=True,
            timeout=15,
        )
    latency_ms = int((perf_counter() - start) * 1000)

    if page.status == 404:
        return HttpScrapeFailure(reason="not_found", latency_ms=latency_ms)
    if page.status >= 400:
        waf = detect_waf(
            status=page.status,
            headers=dict(page.headers),
            body_excerpt=body_excerpt(page.body),
        )
        if waf == "cloudflare":
            return HttpScrapeFailure(
                reason="protected_cloudflare",
                detected_protections=["cloudflare"],
                latency_ms=latency_ms,
            )
        if waf in TERMINAL_WAFS:
            return HttpScrapeFailure(
                reason="site_not_supported",
                detected_protections=[waf],
                latency_ms=latency_ms,
            )
        return HttpScrapeFailure(reason="upstream_error", latency_ms=latency_ms)

    extracted = await _extractor.extract(html=str(page.body), source_url=str(page.url))
    snapshot_key, snapshot_truncated = await persist_snapshot(
        user_id=deps.user_id,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        raw_html=extracted.raw_html,
    )

    return HttpScrapeOk(
        url=str(page.url),
        markdown=extracted.markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
        latency_ms=int((perf_counter() - start) * 1000),
    )
