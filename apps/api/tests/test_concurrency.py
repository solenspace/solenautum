from __future__ import annotations

import asyncio

import pytest

from app.concurrency import browser_slot


@pytest.mark.asyncio
async def test_browser_slot_releases_on_exception() -> None:
    async def _try_in_slot() -> None:
        async with browser_slot():
            raise RuntimeError("simulated tool failure")

    with pytest.raises(RuntimeError):
        await _try_in_slot()

    # If the slot didn't release, this acquire would hang forever.
    async with asyncio.timeout(1.0):
        async with browser_slot():
            pass


@pytest.mark.asyncio
async def test_browser_slot_serializes_at_capacity() -> None:
    # Global ceiling is 8; spawn 9 holders and prove that no more than 8
    # are inside the slot at any moment. A counter incremented on entry
    # and decremented on exit must never exceed the ceiling.
    in_flight = 0
    peak = 0

    async def _hold() -> None:
        nonlocal in_flight, peak
        async with browser_slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1

    tasks = [asyncio.create_task(_hold()) for _ in range(9)]
    await asyncio.gather(*tasks)

    assert peak <= 8, f"slot allowed {peak} concurrent holders, ceiling is 8"
    assert peak == 8, f"slot did not saturate the ceiling: peak={peak}"
    assert in_flight == 0, "slot leaked: holders still recorded after gather"
