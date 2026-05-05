"""Invariant 12 — provider switch fires only on 429/5xx, never on tool-arg
failures or other 4xx. The chain is the only place fallback logic lives.
"""

from __future__ import annotations

import httpx
import pytest

from app.llm.chain import LLMProviderChain


class _FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def model(self) -> _FakeModel:
        return _FakeModel(self.name)


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("upstream", request=request, response=response)


@pytest.mark.asyncio
async def test_returns_primary_when_no_error() -> None:
    chain = LLMProviderChain(primary=_FakeProvider("primary"), fallback=_FakeProvider("fallback"))
    calls: list[str] = []

    async def _run(model: _FakeModel) -> str:
        calls.append(model.name)
        return model.name

    assert await chain.with_fallback(_run) == "primary"
    assert calls == ["primary"]


@pytest.mark.asyncio
async def test_falls_back_on_429() -> None:
    chain = LLMProviderChain(primary=_FakeProvider("primary"), fallback=_FakeProvider("fallback"))
    calls: list[str] = []

    async def _run(model: _FakeModel) -> str:
        calls.append(model.name)
        if model.name == "primary":
            raise _http_status_error(429)
        return model.name

    assert await chain.with_fallback(_run) == "fallback"
    assert calls == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_falls_back_on_503() -> None:
    chain = LLMProviderChain(primary=_FakeProvider("primary"), fallback=_FakeProvider("fallback"))

    async def _run(model: _FakeModel) -> str:
        if model.name == "primary":
            raise _http_status_error(503)
        return model.name

    assert await chain.with_fallback(_run) == "fallback"


@pytest.mark.asyncio
async def test_does_not_fall_back_on_400() -> None:
    """Invariant 12 — tool-arg validation failures are 4xx and must NOT
    trigger a provider switch.
    """
    chain = LLMProviderChain(primary=_FakeProvider("primary"), fallback=_FakeProvider("fallback"))

    async def _run(model: _FakeModel) -> str:
        if model.name == "primary":
            raise _http_status_error(400)
        return model.name

    with pytest.raises(httpx.HTTPStatusError):
        await chain.with_fallback(_run)


@pytest.mark.asyncio
async def test_does_not_fall_back_on_business_exception() -> None:
    """A non-HTTP exception (e.g. ValueError) propagates immediately."""
    chain = LLMProviderChain(primary=_FakeProvider("primary"), fallback=_FakeProvider("fallback"))

    async def _run(model: _FakeModel) -> str:
        raise ValueError("malformed tool args")

    with pytest.raises(ValueError, match="malformed tool args"):
        await chain.with_fallback(_run)
