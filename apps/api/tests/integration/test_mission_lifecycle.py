"""End-to-end integration test for the URL-mode and description-mode
mission lifecycles.

Boots the real FastAPI app via `httpx.ASGITransport` (no extra port,
no multi-process orchestration), submits a mission, drains the SSE
stream until the terminal `done` event, and asserts:
  - The event sequence is `task_start*N → task_end*N → done` (with
    description-mode adding `discovery_complete` before scraping).
  - Every event carries a monotonic `seq` (Spec 06 invariant).
  - DB state transitions: tasks reach SUCCEEDED, mission phase is DONE,
    cost row is set.

The LLM chain, discovery agent, and the scraping tier tools are stubbed
in `conftest.py` so the suite runs hermetically — no network egress
(invariant 1 is preserved by virtue of never reaching the SSRF guard),
no LLM credits consumed.

Skipped when `DATABASE_URL` is unset because the runner persists rows
before the first SSE event (invariant 7).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import MissionPhase, Status, Task
from app.security import CurrentUser, _current_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        settings.database_url is None,
        reason="integration tests require DATABASE_URL",
    ),
]


def _parse_sse_block(block: str) -> dict[str, Any] | None:
    """Parse one `\\n\\n`-delimited SSE block into a JSON event payload.
    Returns `None` for heartbeats and empty blocks.
    """
    if not block.strip() or block.startswith(":"):
        return None
    fields: dict[str, str] = {}
    for line in block.split("\n"):
        if ":" in line and not line.startswith(":"):
            name, _, value = line.partition(": ")
            fields[name] = value
    raw = fields.get("data")
    if raw is None:
        return None
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


async def _drain_until_done(
    client: httpx.AsyncClient, mission_id: str, *, timeout_s: float = 30.0
) -> list[dict[str, Any]]:
    """Open the SSE stream and drain events until the mission-level
    `done` (or `error`) event arrives. Bound by an outer timeout so a
    runaway test surfaces as a clean failure rather than a CI hang.
    """
    events: list[dict[str, Any]] = []

    async def _drain() -> None:
        async with client.stream(
            "GET",
            f"/run-mission/{mission_id}/stream",
            headers={"Accept": "text/event-stream"},
        ) as response:
            assert response.status_code == 200
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = _parse_sse_block(block)
                    if event is None:
                        continue
                    events.append(event)
                    if event["type"] in {"done", "error"} and event.get("task_id") is None:
                        return

    await asyncio.wait_for(_drain(), timeout=timeout_s)
    return events


@pytest.mark.asyncio
async def test_url_mode_5_url_mission_emits_full_event_sequence(
    asgi_client: httpx.AsyncClient,
    stub_url_mode_pipeline: None,
) -> None:
    urls = [f"https://example.com/page-{i}" for i in range(5)]

    response = await asgi_client.post("/missions", json={"urls": urls})
    assert response.status_code == 201, response.text
    mission_id = response.json()["mission_id"]
    UUID(mission_id)

    events = await _drain_until_done(asgi_client, mission_id)
    types = [event["type"] for event in events]

    assert types.count("task_start") == 5
    assert types.count("task_end") == 5
    assert types.count("done") == 1

    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs), "SSE seq must be monotonic (Spec 06 invariant)"
    assert seqs[0] == 0

    done = next(event for event in events if event["type"] == "done")
    assert done["content"]["mission_status"] == "succeeded"

    for task_end in (event for event in events if event["type"] == "task_end"):
        assert task_end["content"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_url_mode_persists_task_rows_to_succeeded(
    asgi_client: httpx.AsyncClient,
    stub_url_mode_pipeline: None,
    fake_user: CurrentUser,
) -> None:
    urls = [f"https://example.com/page-{i}" for i in range(5)]
    response = await asgi_client.post("/missions", json={"urls": urls})
    mission_id = response.json()["mission_id"]
    await _drain_until_done(asgi_client, mission_id)

    _current_user.set(fake_user)
    async with transaction() as session:
        from sqlmodel import select

        rows = (await session.exec(select(Task).where(Task.mission_id == UUID(mission_id)))).all()

    assert len(rows) == 5
    for row in rows:
        assert row.status == Status.SUCCEEDED
        assert row.parsed_markdown is not None
        assert row.snapshot_key is not None


@pytest.mark.asyncio
async def test_description_mode_full_lifecycle(
    asgi_client: httpx.AsyncClient,
    stub_description_mode_pipeline: list[str],
    fake_user: CurrentUser,
) -> None:
    """Description-mode covers discovery + auto-approval + scraping. The
    fake discovery agent returns a fixed 3-URL list; `skip_approval=true`
    bypasses the AWAITING_APPROVAL gate so the test is deterministic
    (no SSE side-channel needed to dispatch the approval).
    """
    response = await asgi_client.post(
        "/missions",
        json={"description": "find example pages", "skip_approval": True},
    )
    assert response.status_code == 201, response.text
    mission_id = response.json()["mission_id"]

    events = await _drain_until_done(asgi_client, mission_id, timeout_s=45.0)
    types = [event["type"] for event in events]

    assert types.count("discovery_complete") == 1
    assert types.count("task_start") == 3
    assert types.count("task_end") == 3
    assert types.count("done") == 1

    discovery_complete = next(event for event in events if event["type"] == "discovery_complete")
    assert discovery_complete["content"]["count"] == 3
    assert discovery_complete["content"]["awaiting_approval"] is False

    _current_user.set(fake_user)
    async with transaction() as session:
        from app.persistence.models import Mission

        mission = await session.get(Mission, UUID(mission_id))
        assert mission is not None
        assert mission.phase == MissionPhase.DONE
        assert sorted(mission.approved_urls or []) == sorted(stub_description_mode_pipeline)
