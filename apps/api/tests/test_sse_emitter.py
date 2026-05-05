"""Spec 06 contract proofs — invariants 4 (single queue, monotonic seq) and 5
(every emitted event lands in the ring buffer; replay returns exactly the
events past `Last-Event-ID`; resume_lost fires when the buffer no longer
covers the requested resume point).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.sse import SseEmitter
from autumn_sse_protocol import SseEvent


def _ev(
    mission_id: UUID,
    type_: str,
    *,
    task_id: UUID | None = None,
    content: Any | None = None,
) -> SseEvent:
    payload: dict[str, Any] = {
        "type": type_,
        "content": content,
        "mission_id": str(mission_id),
        "seq": 0,  # rewritten by emit
    }
    if task_id is not None:
        payload["task_id"] = str(task_id)
    return SseEvent.model_validate(payload)


def _parse_lines(chunk: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in chunk.decode().split("\n"):
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(": ")
        out[name] = value
    return out


@pytest.mark.asyncio
async def test_emits_in_order_with_monotonic_seq() -> None:
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    await em.emit(
        _ev(
            mission,
            "task_start",
            task_id=task,
            content={"url": "https://example.test/", "tier": "http"},
        ),
    )
    await em.emit(
        _ev(mission, "task_end", task_id=task, content={"status": "succeeded"}),
    )
    await em.emit(_ev(mission, "done", content={"mission_status": "succeeded"}))

    seqs: list[int] = []
    async with em.stream(mission, last_event_id=None) as iterator:
        async for chunk in iterator:
            parsed = _parse_lines(chunk)
            if "id" in parsed:
                seqs.append(int(parsed["id"]))

    assert seqs == [0, 1, 2]


@pytest.mark.asyncio
async def test_replay_resume_returns_events_after_last_event_id() -> None:
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    for _ in range(3):
        await em.emit(
            _ev(
                mission,
                "task_end",
                task_id=task,
                content={"status": "succeeded"},
            ),
        )
    await em.emit(_ev(mission, "done", content={"mission_status": "succeeded"}))

    seqs: list[int] = []
    async with em.stream(mission, last_event_id=1) as iterator:
        async for chunk in iterator:
            parsed = _parse_lines(chunk)
            if "id" in parsed:
                seqs.append(int(parsed["id"]))

    assert seqs == [2, 3]


@pytest.mark.asyncio
async def test_resume_lost_when_buffer_outran_last_event_id() -> None:
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    # 220 token events evict events 0..19 from a 200-deep ring buffer.
    for _ in range(220):
        await em.emit(_ev(mission, "token", task_id=task, content="t"))

    seen_codes: list[str] = []
    async with em.stream(mission, last_event_id=5) as iterator:
        async for chunk in iterator:
            parsed = _parse_lines(chunk)
            if "data" not in parsed:
                continue
            data = json.loads(parsed["data"])
            if data.get("type") == "error":
                seen_codes.append(data["content"]["code"])
                break

    assert "resume_lost" in seen_codes


@pytest.mark.asyncio
async def test_replay_when_last_event_id_equals_oldest_minus_one() -> None:
    """Boundary case — the buffer covers exactly from `last_event_id + 1`.
    Should replay everything in the buffer, not return resume_lost.
    """
    em = SseEmitter()
    mission = uuid4()
    task = uuid4()

    for _ in range(201):  # one event evicted
        await em.emit(_ev(mission, "token", task_id=task, content="t"))

    # Buffer holds seqs [1..200]; last_event_id=0 means "give me >0".
    seqs: list[int] = []
    async with em.stream(mission, last_event_id=0) as iterator:
        async for chunk in iterator:
            parsed = _parse_lines(chunk)
            if "id" in parsed:
                seqs.append(int(parsed["id"]))
            if len(seqs) >= 200:
                break

    assert seqs == list(range(1, 201))
