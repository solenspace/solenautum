"""Invariant 1 — every URL that reaches the HTTP-tier tool passes through
`assert_safe_url`, blocking SSRF (loopback, RFC1918, link-local) before any
network egress. Live-network smoke for the Scrapling+Crawl4AI happy path
lives in an opt-in integration suite, not the unit tier.
"""

from __future__ import annotations

import pytest

from app.security import UrlNotAllowed
from app.tools.http import HttpScrapeArgs, HttpToolDeps, scrape_http


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
async def test_scrape_http_blocks_private_addresses(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_http(
            HttpToolDeps(robots_override=False),
            HttpScrapeArgs(url=url),
        )


@pytest.mark.asyncio
async def test_scrape_http_rejects_non_http_scheme() -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_http(
            HttpToolDeps(robots_override=False),
            HttpScrapeArgs(url="file:///etc/passwd"),
        )
