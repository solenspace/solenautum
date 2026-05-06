"""Invariant 1 — the dynamic tool's `assert_safe_url` runs before the
browser session opens, so SSRF blocks fire without spawning Playwright.
Live browser-tier scrapes live in an opt-in integration suite, not
here.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.security import UrlNotAllowed
from app.tools.dynamic import DynamicDeps, DynamicScrapeArgs, scrape_dynamic


def _deps() -> DynamicDeps:
    return DynamicDeps(
        user_id="user_test",
        mission_id=uuid4(),
        task_id=uuid4(),
        robots_override=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
async def test_scrape_dynamic_blocks_private_addresses(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_dynamic(_deps(), DynamicScrapeArgs(url=url))


@pytest.mark.asyncio
async def test_scrape_dynamic_rejects_non_http_scheme() -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_dynamic(_deps(), DynamicScrapeArgs(url="file:///etc/passwd"))
