"""End-to-end smoke for the `/run-mission` route. Validates the full SSE
event sequence (task_start -> task_end:succeeded -> done:succeeded), the
mission/task row state in Postgres, and `tasks.parsed_markdown` matches the
fixture.

LLM and network are stubbed so the test runs hermetically:
- `app.tools.http.scrape_http` is replaced with a deterministic fake result.
- `app.agent.build_agent` is replaced with a fake agent whose `.run()` calls
  the (stubbed) tool once and returns a MissionResult — exercising the
  runner's closure-capture path and SSE pipeline without an LLM round trip.

DB-dependent assertions skip when `DATABASE_URL` is unset.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.agent import MissionResult
from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import Status, Task
from app.persistence.repository import UserRepository
from app.security import CurrentUser, _current_user, require_user
from app.tools.http import HttpScrapeArgs, HttpScrapeResult, HttpToolDeps

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; route smoke needs a real Postgres",
)


_FIXTURE_USER_ID = "user_test_route"
_FIXTURE_URL = "https://example.com/"
_FIXTURE_MARKDOWN = "# Hello Autumn\n\nThis is a Spec 07 fixture page.\n"


@dataclass
class _FakeAgentResult:
    output: MissionResult


class _FakeAgent:
    def __init__(self, last_scrape: list[HttpScrapeResult]) -> None:
        self._last_scrape = last_scrape

    async def run(self, url: str, *, model: Any, deps: HttpToolDeps) -> _FakeAgentResult:
        # Importing locally so the patch applied via fixture is in effect.
        from app.tools import http as http_tool

        result = await http_tool.scrape_http(deps, HttpScrapeArgs(url=url))
        self._last_scrape.append(result)
        return _FakeAgentResult(
            output=MissionResult(
                summary="Fixture page parsed successfully.",
                primary_url=result.url,
                markdown_excerpt=result.markdown[:500],
            ),
        )


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_route")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="route@example.com")


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeResult:
        return HttpScrapeResult(
            url=args.url,
            markdown=_FIXTURE_MARKDOWN,
            raw_html=b"<html>fixture</html>",
            latency_ms=42,
        )

    def _fake_build_agent() -> tuple[_FakeAgent, list[HttpScrapeResult]]:
        last_scrape: list[HttpScrapeResult] = []
        return _FakeAgent(last_scrape), last_scrape

    monkeypatch.setattr("app.tools.http.scrape_http", _fake_scrape)
    monkeypatch.setattr("app.runner.build_agent", _fake_build_agent)


@pytest.fixture
def client(fake_user: CurrentUser, seed_user: None, patch_pipeline: None) -> Iterator[TestClient]:
    from app.main import app

    app.dependency_overrides[require_user] = lambda: fake_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_user, None)


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        lines = {}
        for line in block.split("\n"):
            if ":" in line and not line.startswith(":"):
                name, _, value = line.partition(": ")
                lines[name] = value
        if "data" in lines:
            events.append(json.loads(lines["data"]))
    return events


@pytest.mark.asyncio
async def test_run_mission_streams_terminal_events(client: TestClient) -> None:
    response = client.get(
        "/run-mission",
        params={"url": _FIXTURE_URL},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    types = [event["type"] for event in events]
    assert types == ["task_start", "task_end", "done"]

    task_end = next(e for e in events if e["type"] == "task_end")
    assert task_end["content"]["status"] == "succeeded"
    assert _FIXTURE_MARKDOWN.startswith(task_end["content"]["preview"][:20])

    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "succeeded"

    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert seqs[0] == 0


@pytest.mark.asyncio
async def test_run_mission_persists_full_markdown(
    client: TestClient, fake_user: CurrentUser
) -> None:
    response = client.get(
        "/run-mission",
        params={"url": _FIXTURE_URL},
        headers={"Authorization": "Bearer fake"},
    )
    events = _parse_sse(response.text)
    mission_id = events[0]["mission_id"]

    _current_user.set(fake_user)
    async with transaction() as session:
        from sqlmodel import select

        rows = (await session.exec(select(Task).where(Task.mission_id == mission_id))).all()
    assert len(rows) == 1
    task = rows[0]
    assert task.status == Status.SUCCEEDED
    assert task.parsed_markdown == _FIXTURE_MARKDOWN
    assert task.latency_ms == 42
