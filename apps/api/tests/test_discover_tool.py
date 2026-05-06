"""`discover_urls` tool — per-mission single-call cap, SSRF defense-in-
depth, and `url_discovered` event emission.

`emitter.emit` writes to a per-mission queue/buffer; tests drain the
buffer to assert the events the tool emitted, since each test creates a
fresh `mission_id` and the buffer is keyed by mission.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.search import DiscoveredUrl
from app.sse import emitter
from app.tools.discover import (
    DiscoverArgs,
    DiscoverDeps,
    DiscoveryFailure,
    DiscoveryOk,
    discover_urls,
)


def _drain_buffer(mission_id: UUID) -> list[dict[str, Any]]:
    """Snapshot the per-mission ring-buffer contents. The emitter populates
    this in `emit()`; we don't pop the queue because that would race with
    the in-flight tool call.
    """
    state = emitter._missions.get(mission_id)
    return [payload for _, payload in state.buffer] if state is not None else []


def _evict(mission_id: UUID) -> None:
    """Drop the mission's emitter state so a follow-up test starts clean."""
    emitter._missions.pop(mission_id, None)


@pytest.mark.asyncio
async def test_happy_path_emits_url_discovered_per_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_id = uuid4()
    fake = [
        DiscoveredUrl(url="https://example.com/a", score=0.9, source="tavily"),
        DiscoveredUrl(url="https://example.com/b", score=0.6, source="tavily"),
        DiscoveredUrl(url="https://example.com/c", score=0.3, source="tavily"),
    ]

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return fake

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    result = await discover_urls(
        DiscoverDeps(user_id="user_test", mission_id=mission_id),
        DiscoverArgs(query="frameworks"),
    )

    assert isinstance(result, DiscoveryOk)
    assert len(result.urls) == 3
    events = _drain_buffer(mission_id)
    types = [e["type"] for e in events]
    assert types == ["url_discovered", "url_discovered", "url_discovered"]
    assert events[0]["content"]["url"] == "https://example.com/a"
    assert events[0]["content"]["source"] == "tavily"
    assert events[0]["content"]["score"] == pytest.approx(0.9)
    _evict(mission_id)


@pytest.mark.asyncio
async def test_second_call_in_same_context_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-mission cost cap: the agent's system prompt instructs one call;
    the contextvar enforcement is the safety net.
    """
    mission_id = uuid4()
    fake = [DiscoveredUrl(url="https://example.com/", score=0.5, source="tavily")]

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return fake

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    deps = DiscoverDeps(user_id="user_test", mission_id=mission_id)
    args = DiscoverArgs(query="x")

    # Both calls execute in the same async task → same contextvar copy.
    first = await discover_urls(deps, args)
    second = await discover_urls(deps, args)

    assert isinstance(first, DiscoveryOk)
    assert isinstance(second, DiscoveryFailure)
    assert second.reason == "upstream_error"
    assert "discovery already called" in (second.detail or "")
    _evict(mission_id)


@pytest.mark.asyncio
async def test_concurrent_missions_have_independent_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ContextVars are per-task. Two concurrent mission contexts each get
    their own first-call success.
    """
    fake = [DiscoveredUrl(url="https://example.com/", score=0.5, source="tavily")]

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return fake

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    mid_a, mid_b = uuid4(), uuid4()

    async def _run(mid: UUID) -> Any:
        return await discover_urls(
            DiscoverDeps(user_id="user_test", mission_id=mid),
            DiscoverArgs(query="x"),
        )

    a, b = await asyncio.gather(_run(mid_a), _run(mid_b))
    assert isinstance(a, DiscoveryOk)
    assert isinstance(b, DiscoveryOk)
    _evict(mid_a)
    _evict(mid_b)


@pytest.mark.asyncio
async def test_tavily_5xx_returns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mission_id = uuid4()

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        raise RuntimeError("tavily 503")

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    result = await discover_urls(
        DiscoverDeps(user_id="user_test", mission_id=mission_id),
        DiscoverArgs(query="x"),
    )

    assert isinstance(result, DiscoveryFailure)
    assert result.reason == "upstream_error"
    assert "tavily 503" in (result.detail or "")
    _evict(mission_id)


@pytest.mark.asyncio
async def test_zero_results_returns_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_id = uuid4()

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return []

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    result = await discover_urls(
        DiscoverDeps(user_id="user_test", mission_id=mission_id),
        DiscoverArgs(query="asdfqwerzxcv"),
    )

    assert isinstance(result, DiscoveryFailure)
    assert result.reason == "no_results"
    _evict(mission_id)


@pytest.mark.asyncio
async def test_unsafe_urls_are_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense-in-depth: a poisoned Tavily response containing an SSRF
    target (e.g. AWS metadata IP) is silently dropped before
    `url_discovered` emits or the result returns.
    """
    mission_id = uuid4()
    safe = DiscoveredUrl(url="https://example.com/safe", score=0.9, source="tavily")
    unsafe = DiscoveredUrl(
        url="http://169.254.169.254/latest/meta-data/", score=0.8, source="tavily"
    )

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return [safe, unsafe]

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    result = await discover_urls(
        DiscoverDeps(user_id="user_test", mission_id=mission_id),
        DiscoverArgs(query="x"),
    )

    assert isinstance(result, DiscoveryOk)
    assert len(result.urls) == 1
    assert result.urls[0].url == "https://example.com/safe"
    events = _drain_buffer(mission_id)
    assert len(events) == 1
    assert events[0]["content"]["url"] == "https://example.com/safe"
    _evict(mission_id)


@pytest.mark.asyncio
async def test_all_unsafe_collapses_to_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If every URL fails the SSRF check, the user sees `no_results`
    (the safer UX than silently saying "we found 5 things, none of them
    safe").
    """
    mission_id = uuid4()
    unsafe = [
        DiscoveredUrl(url="http://127.0.0.1/", score=0.9, source="tavily"),
        DiscoveredUrl(url="http://10.0.0.1/", score=0.8, source="tavily"),
    ]

    async def _fake_search(self: Any, query: str, *, max_results: int = 20) -> list[DiscoveredUrl]:
        return unsafe

    monkeypatch.setattr("app.tools.discover.TavilyProvider.search", _fake_search)

    result = await discover_urls(
        DiscoverDeps(user_id="user_test", mission_id=mission_id),
        DiscoverArgs(query="x"),
    )

    assert isinstance(result, DiscoveryFailure)
    assert result.reason == "no_results"
    _evict(mission_id)
