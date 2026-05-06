"""Spec 10 — per-mission ceilings layer over the global slots.

`MissionSemaphores` exposes HTTP-20 / browser-3. A mission spawning more
than the per-mission cap must serialize the excess; the test counts
peak in-flight holders inside the slot and asserts it never exceeds the
cap.
"""

from __future__ import annotations

import asyncio

import pytest

from app.concurrency import (
    MissionSemaphores,
    current_mission_semaphores,
    with_mission_semaphores,
)


@pytest.mark.asyncio
async def test_per_mission_http_caps_at_20() -> None:
    sems = MissionSemaphores.fresh()
    in_flight = 0
    peak = 0

    async def _job() -> None:
        nonlocal in_flight, peak
        async with with_mission_semaphores(sems), current_mission_semaphores().http_slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await asyncio.gather(*[_job() for _ in range(40)])

    assert peak <= 20, f"per-mission http cap breached: peak={peak}"
    assert peak == 20, f"per-mission http cap did not saturate: peak={peak}"
    assert in_flight == 0, "slot leaked: holders still recorded after gather"


@pytest.mark.asyncio
async def test_per_mission_browser_caps_at_3() -> None:
    sems = MissionSemaphores.fresh()
    in_flight = 0
    peak = 0

    async def _job() -> None:
        nonlocal in_flight, peak
        async with with_mission_semaphores(sems), current_mission_semaphores().browser_slot():
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1

    await asyncio.gather(*[_job() for _ in range(10)])

    assert peak <= 3, f"per-mission browser cap breached: peak={peak}"
    assert peak == 3, f"per-mission browser cap did not saturate: peak={peak}"
    assert in_flight == 0, "slot leaked: holders still recorded after gather"


@pytest.mark.asyncio
async def test_layered_slot_releases_on_cancellation() -> None:
    """A cancelled job inside `http_slot()` releases both the per-mission
    and the global semaphore via the stacked `async with` exits.
    """
    sems = MissionSemaphores.fresh()

    async def _hold_then_cancel() -> None:
        async with with_mission_semaphores(sems), current_mission_semaphores().http_slot():
            raise RuntimeError("simulated tool failure")

    with pytest.raises(RuntimeError):
        await _hold_then_cancel()

    # If either slot leaked, this re-acquire would hang.
    async with (
        asyncio.timeout(1.0),
        with_mission_semaphores(sems),
        current_mission_semaphores().http_slot(),
    ):
        pass


@pytest.mark.asyncio
async def test_current_mission_semaphores_falls_back_outside_binding() -> None:
    """Tier tools called without a mission scope (e.g. a unit test that
    bypasses the runner) must still get a working slot — the fallback
    returns a fresh `MissionSemaphores` instance whose globals still
    apply.
    """
    fallback = current_mission_semaphores()
    async with fallback.http_slot():
        pass  # no hang, no error


@pytest.mark.asyncio
async def test_per_task_context_propagates_into_taskgroup_children() -> None:
    """`with_mission_semaphores` binds via `ContextVar`. asyncio's
    `TaskGroup.create_task` propagates the calling context to children,
    so per-task coroutines inherit the parent mission's semaphores
    without any explicit threading.
    """
    sems = MissionSemaphores.fresh()
    seen_identity: list[int] = []

    async def _child() -> None:
        seen_identity.append(id(current_mission_semaphores()))

    async with with_mission_semaphores(sems), asyncio.TaskGroup() as tg:
        for _ in range(5):
            tg.create_task(_child())

    assert len(seen_identity) == 5
    assert all(identity == id(sems) for identity in seen_identity)
