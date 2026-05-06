"""Spec 10 — SSE heartbeats keep proxies (Cloudflare / Fly / Render)
from killing idle event streams.

The heartbeat is implemented as a per-stream `asyncio.wait_for`
timeout in `SseEmitter.stream`: when no event arrives within
`_HEARTBEAT_INTERVAL_S`, the iterator yields one
`b": heartbeat\\n\\n"` SSE comment and resumes waiting. Heartbeats
do not consume `seq` (they don't carry an `id:` line); reconnects
with `Last-Event-ID` ignore them.

We patch `_HEARTBEAT_INTERVAL_S` down to 0.05s so the test runs in
under a second instead of the production 15s.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.sse import SseEmitter
from autumn_sse_protocol import SseEvent


@pytest.mark.asyncio
async def test_heartbeat_fires_when_stream_idles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attached stream that idles past `_HEARTBEAT_INTERVAL_S` yields
    a heartbeat byte string. Production interval is 15s; we patch it to
    0.05s for the test.
    """
    monkeypatch.setattr("app.sse._HEARTBEAT_INTERVAL_S", 0.05)

    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    # Emit one event so the per-mission state exists. Without this, the
    # stream would synthesize `resume_lost` (the consumer attached
    # before any producer wrote) and close immediately.
    await em.emit(
        SseEvent.model_validate(
            {
                "type": "task_start",
                "content": {"url": "https://example.test/", "tier": "http"},
                "mission_id": str(mission),
                "task_id": str(task),
                "seq": 0,
            },
        ),
    )

    chunks: list[bytes] = []
    # Resume past the seeded event so the iterator skips replay and
    # blocks on the live queue, where the heartbeat timeout fires.
    async with em.stream(mission, last_event_id=0) as iterator:
        try:
            async with asyncio.timeout(0.5):
                async for chunk in iterator:
                    chunks.append(chunk)
                    if chunk == b": heartbeat\n\n":
                        break
        except TimeoutError:  # pragma: no cover — 0.5s >> 0.05s heartbeat
            pass

    assert any(chunk == b": heartbeat\n\n" for chunk in chunks), f"no heartbeat in {chunks!r}"


@pytest.mark.asyncio
async def test_heartbeat_does_not_consume_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat comments are written without an `id:` line, so a
    well-behaved EventSource client does not advance `Last-Event-ID`
    past the last real event when one fires. Test by ensuring the next
    real event after a heartbeat carries the next monotonic seq.
    """
    monkeypatch.setattr("app.sse._HEARTBEAT_INTERVAL_S", 0.05)

    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    await em.emit(
        SseEvent.model_validate(
            {
                "type": "task_start",
                "content": {"url": "https://example.test/", "tier": "http"},
                "mission_id": str(mission),
                "task_id": str(task),
                "seq": 0,
            },
        ),
    )

    chunks: list[bytes] = []
    saw_heartbeat = False

    async def _emit_after_heartbeat() -> None:
        # Wait long enough for at least one heartbeat to land in `chunks`,
        # then push a real event whose seq must increment past 0.
        await asyncio.sleep(0.15)
        await em.emit(
            SseEvent.model_validate(
                {
                    "type": "task_end",
                    "content": {"status": "succeeded"},
                    "mission_id": str(mission),
                    "task_id": str(task),
                    "seq": 0,
                },
            ),
        )

    async with asyncio.TaskGroup() as tg, em.stream(mission, last_event_id=0) as iterator:
        tg.create_task(_emit_after_heartbeat())
        try:
            async with asyncio.timeout(1.0):
                async for chunk in iterator:
                    chunks.append(chunk)
                    if chunk == b": heartbeat\n\n":
                        saw_heartbeat = True
                    if b"event: task_end" in chunk:
                        break
        except TimeoutError:  # pragma: no cover
            pass

    assert saw_heartbeat, f"no heartbeat in {chunks!r}"
    real_event_chunk = next(c for c in chunks if b"event: task_end" in c)
    # Heartbeat carried no `id:` line; the next real event should still be seq=1
    # (one increment past the seeded seq=0), proving heartbeats did not bump
    # the per-mission seq counter.
    assert b"id: 1\n" in real_event_chunk, real_event_chunk
