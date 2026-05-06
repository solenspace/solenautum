"""Invariant 1 — every URL that reaches the HTTP-tier tool passes through
`assert_safe_url`, blocking SSRF (loopback, RFC1918, link-local) before any
network egress. Live-network smoke for the Scrapling+Crawl4AI happy path
lives in an opt-in integration suite, not the unit tier.

After Spec 09, the tool returns a discriminated union (`HttpScrapeOk |
HttpScrapeFailure`) instead of raising on 4xx; the agent uses the
failure `reason` to choose escalation.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.security import UrlNotAllowed
from app.tools.http import HttpScrapeArgs, HttpScrapeFailure, HttpToolDeps, scrape_http


def _deps() -> HttpToolDeps:
    return HttpToolDeps(
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
async def test_scrape_http_blocks_private_addresses(url: str) -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_http(_deps(), HttpScrapeArgs(url=url))


@pytest.mark.asyncio
async def test_scrape_http_rejects_non_http_scheme() -> None:
    with pytest.raises(UrlNotAllowed):
        await scrape_http(_deps(), HttpScrapeArgs(url="file:///etc/passwd"))


class _FakePage:
    """Minimal stand-in for `scrapling.engines.toolbelt.custom.Response`."""

    def __init__(self, *, url: str, status: int, headers: dict[str, str], body: str = "") -> None:
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body


@pytest.mark.asyncio
async def test_scrape_http_returns_protected_cloudflare_on_cf_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 with Cloudflare fingerprints is surfaced as a typed failure
    (reason=protected_cloudflare), not raised. The agent uses this to
    escalate to the stealth tier.
    """

    async def _fake_get(url: str, **_kw: Any) -> _FakePage:
        return _FakePage(
            url=url,
            status=403,
            headers={"server": "cloudflare", "cf-ray": "abc123"},
            body="",
        )

    # `assert_robots_allows` reads the live robots.txt over the network; for
    # public hosts that have a permissive robots, this is fine to call. We
    # short-circuit it here so the test stays fully hermetic.
    async def _allow_all(url: str, *, robots_override: bool = False) -> None:
        return None

    monkeypatch.setattr("app.tools.http.AsyncFetcher.get", _fake_get)
    monkeypatch.setattr("app.tools.http.assert_robots_allows", _allow_all)

    result = await scrape_http(_deps(), HttpScrapeArgs(url="https://example.com/blocked"))

    assert isinstance(result, HttpScrapeFailure)
    assert result.reason == "protected_cloudflare"
    assert result.detected_protections == ["cloudflare"]
    assert result.latency_ms >= 0
