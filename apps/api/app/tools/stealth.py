"""Stealth tier — Camoufox via Scrapling's `StealthyFetcher`.

Invariant 2: every browser session opens inside `browser_slot()`.

Spec 09 deviation #1: the spec assumes Scrapling 0.3+'s
`AsyncStealthySession` async-context-manager API. The pinned 0.2.99
release exposes only the class-method `StealthyFetcher.async_fetch(...)`.
Same Response shape; same WAF-routing logic.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field
from scrapling.fetchers import StealthyFetcher

from app.concurrency import current_mission_semaphores
from app.extract import MarkdownExtractor
from app.observability import observe
from app.persistence.repository import SelectorRepository
from app.persistence.snapshot import persist_snapshot
from app.security import assert_robots_allows, assert_safe_url
from app.tools._select import select_main_content
from app.tools._storage import ProcessLruStorage
from app.tools._waf import TERMINAL_WAFS, body_excerpt, detect_waf

_extractor = MarkdownExtractor()


class StealthScrapeArgs(BaseModel):
    url: str = Field(..., max_length=2048)


class StealthScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class StealthScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "site_not_supported",
        "javascript_required",
        "upstream_error",
        "not_found",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


StealthScrapeResult = StealthScrapeOk | StealthScrapeFailure


class StealthDeps(BaseModel):
    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


@observe(name="tool.scrape_stealth")  # type: ignore[untyped-decorator]
async def scrape_stealth(deps: StealthDeps, args: StealthScrapeArgs) -> StealthScrapeResult:
    """Fetch with the Camoufox stealth browser. Honors invariants 1, 2, 9, 11."""
    assert_safe_url(args.url)  # invariant 1
    await assert_robots_allows(args.url, robots_override=deps.robots_override)  # invariant 11

    start = perf_counter()

    async with current_mission_semaphores().browser_slot():  # invariant 2 (layered)
        page = await StealthyFetcher.async_fetch(
            args.url,
            headless=True,
            network_idle=True,
            humanize=True,
            # Spec 13: adaptive selector storage threaded into the Adaptor.
            custom_config={
                "auto_match": True,
                "storage": ProcessLruStorage,
                "storage_args": {"url": args.url},
            },
        )

    latency_ms = int((perf_counter() - start) * 1000)

    if page.status == 404:
        return StealthScrapeFailure(reason="not_found", latency_ms=latency_ms)
    if page.status >= 400:
        waf = detect_waf(
            status=page.status,
            headers=dict(page.headers),
            body_excerpt=body_excerpt(page.body),
        )
        if waf in TERMINAL_WAFS:
            return StealthScrapeFailure(
                reason="site_not_supported",
                detected_protections=[waf],
                latency_ms=latency_ms,
            )
        if waf == "cloudflare":
            # Camoufox's bypass did not clear the challenge — likely a
            # JS-challenge variant. Escalate to the dynamic tier.
            return StealthScrapeFailure(
                reason="javascript_required",
                detected_protections=["cloudflare"],
                latency_ms=latency_ms,
            )
        return StealthScrapeFailure(reason="upstream_error", latency_ms=latency_ms)

    domain = urlparse(str(page.url)).hostname or ""
    main_html = await select_main_content(
        page=page,
        domain=domain,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        repo=SelectorRepository(),
    )
    extracted = await _extractor.extract(html=main_html, source_url=str(page.url))
    snapshot_key, snapshot_truncated = await persist_snapshot(
        user_id=deps.user_id,
        mission_id=deps.mission_id,
        task_id=deps.task_id,
        raw_html=extracted.raw_html,
    )

    return StealthScrapeOk(
        url=str(page.url),
        markdown=extracted.markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
        latency_ms=int((perf_counter() - start) * 1000),
    )
