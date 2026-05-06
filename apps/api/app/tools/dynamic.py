"""Dynamic tier — full Playwright via Scrapling's `PlayWrightFetcher`.

JS-rendering terminus. A Cloudflare challenge that survives this tier
surfaces as `upstream_error`, not `javascript_required`, because there
is no further escalation. Invariant 2: browser session inside
`browser_slot()`.

Spec 09 deviation #1: the spec assumes Scrapling 0.3+'s
`AsyncDynamicSession` async-context-manager API. The pinned 0.2.99
exposes only the class-method `PlayWrightFetcher.async_fetch(...)`.
"""

from __future__ import annotations

from time import perf_counter
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel, Field
from scrapling.fetchers import PlayWrightFetcher

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


class DynamicScrapeArgs(BaseModel):
    url: str = Field(..., max_length=2048)
    wait_for_selector: str | None = Field(default=None, max_length=256)


class DynamicScrapeOk(BaseModel):
    status: Literal["ok"] = "ok"
    url: str
    markdown: str
    snapshot_key: str
    snapshot_truncated: bool
    latency_ms: int


class DynamicScrapeFailure(BaseModel):
    status: Literal["failed"] = "failed"
    reason: Literal[
        "site_not_supported",
        "upstream_error",
        "not_found",
        "render_timeout",
    ]
    detected_protections: list[str] = Field(default_factory=list)
    latency_ms: int


DynamicScrapeResult = DynamicScrapeOk | DynamicScrapeFailure


class DynamicDeps(BaseModel):
    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


@observe(name="tool.scrape_dynamic")  # type: ignore[untyped-decorator]
async def scrape_dynamic(deps: DynamicDeps, args: DynamicScrapeArgs) -> DynamicScrapeResult:
    """Fetch with the full Playwright browser. Honors invariants 1, 2, 9, 11."""
    assert_safe_url(args.url)  # invariant 1
    await assert_robots_allows(args.url, robots_override=deps.robots_override)  # invariant 11

    start = perf_counter()

    async with current_mission_semaphores().browser_slot():  # invariant 2 (layered)
        try:
            page = await PlayWrightFetcher.async_fetch(
                args.url,
                headless=True,
                network_idle=True,
                wait_selector=args.wait_for_selector,
                timeout=30_000,
                # Spec 13: adaptive selector storage threaded into the Adaptor.
                custom_config={
                    "auto_match": True,
                    "storage": ProcessLruStorage,
                    "storage_args": {"url": args.url},
                },
            )
        except (PlaywrightTimeoutError, TimeoutError):
            # Both Playwright's own TimeoutError and the builtin TimeoutError
            # (which is what asyncio.TimeoutError is aliased to in 3.11+).
            return DynamicScrapeFailure(
                reason="render_timeout",
                latency_ms=int((perf_counter() - start) * 1000),
            )

    latency_ms = int((perf_counter() - start) * 1000)

    if page.status == 404:
        return DynamicScrapeFailure(reason="not_found", latency_ms=latency_ms)
    if page.status >= 400:
        waf = detect_waf(
            status=page.status,
            headers=dict(page.headers),
            body_excerpt=body_excerpt(page.body),
        )
        if waf in TERMINAL_WAFS:
            return DynamicScrapeFailure(
                reason="site_not_supported",
                detected_protections=[waf],
                latency_ms=latency_ms,
            )
        # Cloudflare survived even the dynamic tier — no further escalation.
        return DynamicScrapeFailure(reason="upstream_error", latency_ms=latency_ms)

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

    return DynamicScrapeOk(
        url=str(page.url),
        markdown=extracted.markdown,
        snapshot_key=snapshot_key,
        snapshot_truncated=snapshot_truncated,
        latency_ms=int((perf_counter() - start) * 1000),
    )
