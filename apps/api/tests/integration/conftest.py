"""Shared fixtures for the integration suite.

Boots the real FastAPI app via `httpx.ASGITransport`, hits the mission
lifecycle end-to-end, and asserts the SSE event sequence + DB state
transitions. The LLM chain and the tier tools are stubbed via
`tests/_shared/fakes.py` so the suite runs hermetically — no LLM credits,
no real network egress, no engagement of the SSRF guard (invariant 1).

Marked `pytest.mark.integration` and skipped when `DATABASE_URL` is unset
because the runner persists rows before the first SSE event (invariant 7).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from app.agent import DiscoveryMissionResult
from app.persistence.repository import UserRepository
from app.search import DiscoveredUrl
from app.security import CurrentUser, _current_user, require_user
from tests._shared.fakes import (
    FakeChain,
    FakeDiscoveryAgent,
    FakeScrapeAgent,
    make_http_scrape_stub,
)

_FIXTURE_USER_ID = "user_integration_lifecycle"
_FIXTURE_MARKDOWN = "# Fixture page\n\nContent rendered by the integration harness.\n"
_FIXTURE_SNAPSHOT_KEY_TEMPLATE = "{user_id}/{mission_id}/{task_id}.html.gz"


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_integration")


@pytest_asyncio.fixture
async def seeded_user(fake_user: CurrentUser) -> None:
    # `users` has no RLS; this write does not require `_current_user` bound.
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="integration@example.com")


@pytest.fixture
def stub_url_mode_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.tools.http.scrape_http",
        make_http_scrape_stub(
            markdown=_FIXTURE_MARKDOWN,
            key_template=_FIXTURE_SNAPSHOT_KEY_TEMPLATE,
        ),
    )
    monkeypatch.setattr("app.runner.build_agent", FakeScrapeAgent)
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: FakeChain())


@pytest.fixture
def stub_description_mode_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    stub_url_mode_pipeline: None,
) -> list[str]:
    """Layer the description-mode discovery stub on top of the URL-mode
    stubs. Returns the discovered URL list so tests can assert it lands
    unchanged on the mission row.
    """
    discovered_urls = [f"https://example.com/discovered/{i}" for i in range(3)]
    discovery_result = DiscoveryMissionResult(
        status="ok",
        urls=[
            DiscoveredUrl(url=u, score=0.9, source="fixture", title=f"Result {i}")
            for i, u in enumerate(discovered_urls)
        ],
    )
    monkeypatch.setattr(
        "app.runner.build_discovery_agent",
        lambda: FakeDiscoveryAgent(result=discovery_result),
    )
    return discovered_urls


@pytest_asyncio.fixture
async def asgi_client(
    fake_user: CurrentUser, seeded_user: None
) -> AsyncIterator[httpx.AsyncClient]:
    """Real FastAPI app, real lifespan, in-process via ASGI transport.

    `app.router.lifespan_context(app)` is essential — it constructs the
    SSE emitter's TaskGroup. Without it, `adopt_runner` raises because no
    group is bound (invariant 3). httpx's ASGITransport does not run
    lifespan automatically.
    """
    from app.main import app

    app.dependency_overrides[require_user] = lambda: fake_user
    transport = httpx.ASGITransport(app=app)
    try:
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client,
            app.router.lifespan_context(app),
        ):
            yield client
    finally:
        app.dependency_overrides.pop(require_user, None)
