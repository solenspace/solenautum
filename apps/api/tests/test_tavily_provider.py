"""TavilyProvider unit tests — `httpx` is monkeypatched so the suite is
hermetic. Covers the happy path, the 5xx propagation, the empty-results
edge case, and the `max_results` cap.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.config import settings
from app.search.tavily import TavilyProvider


class _FakeResponse:
    def __init__(self, *, status_code: int, json_payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._json = json_payload

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            request = httpx.Request("POST", "https://api.tavily.com/search")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"tavily returned {self.status_code}",
                request=request,
                response=response,
            )

    def json(self) -> dict[str, Any]:
        return self._json


class _FakeClient:
    """Stand-in for `httpx.AsyncClient` whose `.post()` returns a canned
    response. Captures the last posted body so tests can assert query
    shape (e.g. the `max_results` cap).
    """

    def __init__(self, *, response: _FakeResponse) -> None:
        self._response = response
        self.last_body: dict[str, Any] | None = None
        self.aclose_called = False

    async def post(self, url: str, *, json: dict[str, Any]) -> _FakeResponse:
        self.last_body = json
        return self._response

    async def aclose(self) -> None:
        self.aclose_called = True


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a fake key so the provider doesn't refuse to call. Reset on
    teardown so other tests don't observe leaked configuration.
    """
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test-key")


@pytest.mark.asyncio
async def test_happy_path_returns_discovered_urls() -> None:
    response = _FakeResponse(
        status_code=200,
        json_payload={
            "results": [
                {
                    "url": "https://a.example.com/post",
                    "title": "Alpha",
                    "score": 0.92,
                    "raw_favicon": "https://a.example.com/fav.ico",
                },
                {
                    "url": "https://b.example.com/article",
                    "title": "Bravo",
                    "score": 0.61,
                    "raw_favicon": None,
                },
                {
                    "url": "https://c.example.com/page",
                    "title": None,
                    "score": 0.33,
                    "raw_favicon": None,
                },
            ]
        },
    )
    client = _FakeClient(response=response)
    provider = TavilyProvider(client=client)  # type: ignore[arg-type]

    urls = await provider.search("frameworks", max_results=10)

    assert len(urls) == 3
    assert urls[0].url == "https://a.example.com/post"
    assert urls[0].title == "Alpha"
    assert urls[0].favicon_url == "https://a.example.com/fav.ico"
    assert urls[0].source == "tavily"
    assert 0.0 <= urls[0].score <= 1.0
    assert urls[2].title is None
    # Caller-owned client must not be aclose()'d by the provider.
    assert client.aclose_called is False


@pytest.mark.asyncio
async def test_5xx_propagates_via_raise_for_status() -> None:
    response = _FakeResponse(status_code=503, json_payload={})
    client = _FakeClient(response=response)
    provider = TavilyProvider(client=client)  # type: ignore[arg-type]

    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("anything")


@pytest.mark.asyncio
async def test_empty_results_returns_empty_list() -> None:
    response = _FakeResponse(status_code=200, json_payload={"results": []})
    client = _FakeClient(response=response)
    provider = TavilyProvider(client=client)  # type: ignore[arg-type]

    urls = await provider.search("nothing")

    assert urls == []


@pytest.mark.asyncio
async def test_max_results_capped_at_20() -> None:
    """The provider enforces the cost cap server-side too. A caller asking
    for 100 must hit the API with 20.
    """
    response = _FakeResponse(status_code=200, json_payload={"results": []})
    client = _FakeClient(response=response)
    provider = TavilyProvider(client=client)  # type: ignore[arg-type]

    await provider.search("noop", max_results=100)

    assert client.last_body is not None
    assert client.last_body["max_results"] == 20


@pytest.mark.asyncio
async def test_score_is_clamped_to_unit_interval() -> None:
    """If Tavily ever returns >1.0 or <0.0 the model's Field constraints
    would otherwise raise; the provider clamps so the agent observes a
    well-formed `DiscoveredUrl`.
    """
    response = _FakeResponse(
        status_code=200,
        json_payload={
            "results": [
                {"url": "https://x.example.com/", "title": "x", "score": 1.4},
                {"url": "https://y.example.com/", "title": "y", "score": -0.1},
            ]
        },
    )
    client = _FakeClient(response=response)
    provider = TavilyProvider(client=client)  # type: ignore[arg-type]

    urls = await provider.search("clamp")

    assert urls[0].score == 1.0
    assert urls[1].score == 0.0


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tavily_api_key", None)
    provider = TavilyProvider()
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        await provider.search("anything")
