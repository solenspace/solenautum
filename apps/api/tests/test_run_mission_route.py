"""End-to-end smoke for the mission lifecycle: `POST /missions` returns
a mission id; `GET /run-mission/{id}/stream` replays the full SSE
sequence (`task_start → task_end:succeeded → done:succeeded`); the
`tasks` row in Postgres carries `parsed_markdown` and `snapshot_key`.

LLM and network are stubbed so the test runs hermetically:
- `app.tools.http.scrape_http` is replaced with a deterministic fake
  result that mirrors the real `HttpScrapeOk` shape (Spec 09 discriminated
  union).
- `app.runner.build_agent` is replaced with a fake agent whose `.run()`
  calls the stubbed tool once and returns a `MissionResult(status="ok",
  ...)` plus an `all_messages()` shape the runner can walk via
  `last_ok_tool_call`.
- `app.runner.LLMProviderChain` is replaced with a stub so the test does
  not depend on `OPENROUTER_API_KEY` / `GROQ_API_KEY`.

DB-dependent assertions skip when `DATABASE_URL` is unset.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.agent import MissionDeps, MissionResult
from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import Status, Task
from app.persistence.repository import UserRepository
from app.security import CurrentUser, _current_user, require_user
from app.tools.http import HttpScrapeArgs, HttpScrapeOk, HttpToolDeps

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; route smoke needs a real Postgres",
)


_FIXTURE_USER_ID = "user_test_route"
_FIXTURE_URL = "https://example.com/"
_FIXTURE_MARKDOWN = "# Hello Autumn\n\nThis is a Spec 07 fixture page.\n"
_FIXTURE_SNAPSHOT_KEY = "user_test_route/fixture/snapshot.html.gz"


@dataclass
class _FakeAgentResult:
    output: MissionResult
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


class _FakeAgent:
    """Stub `Agent` that calls the stubbed tier tool once and returns a
    fake result whose `all_messages()` carries one `ToolReturnPart`
    holding a real `HttpScrapeOk` — so `last_ok_tool_call` recovers
    the snapshot key, markdown, and latency exactly as it would in
    production.
    """

    async def run(self, url: str, *, model: Any, deps: MissionDeps) -> _FakeAgentResult:
        from app.tools import http as http_tool

        http_deps = HttpToolDeps(
            user_id=deps.user_id,
            mission_id=deps.mission_id,
            task_id=deps.task_id,
            robots_override=deps.robots_override,
        )
        tool_result = await http_tool.scrape_http(http_deps, HttpScrapeArgs(url=url))
        # The real Pydantic AI builds these messages around each tool call;
        # last_ok_tool_call only reads `ToolReturnPart.content`, so a
        # minimal one-message history is enough.
        message = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="scrape_http",
                    content=tool_result,
                    tool_call_id="call_1",
                ),
            ],
        )
        return _FakeAgentResult(
            output=MissionResult(
                status="ok",
                summary="Fixture page parsed successfully.",
                primary_url=tool_result.url if tool_result.status == "ok" else url,
                markdown_excerpt=(tool_result.markdown[:500] if tool_result.status == "ok" else ""),
            ),
            messages=[message],
        )


class _FakeChain:
    """Replaces `LLMProviderChain` so the route test does not depend on
    LLM env credentials. Just runs the callable with a sentinel model.
    """

    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_route")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="route@example.com")


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_scrape(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeOk:
        return HttpScrapeOk(
            url=args.url,
            markdown=_FIXTURE_MARKDOWN,
            snapshot_key=_FIXTURE_SNAPSHOT_KEY,
            snapshot_truncated=False,
            latency_ms=42,
        )

    def _fake_build_agent() -> _FakeAgent:
        return _FakeAgent()

    monkeypatch.setattr("app.tools.http.scrape_http", _fake_scrape)
    monkeypatch.setattr("app.runner.build_agent", _fake_build_agent)
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _FakeChain())


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


def _post_and_stream(client: TestClient, urls: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """Submit a mission via POST /missions, then attach via GET stream.
    Returns the mission id and the parsed event list (drained until the
    mission's terminal `done` event).
    """
    start = client.post(
        "/missions",
        json={"urls": urls},
        headers={"Authorization": "Bearer fake"},
    )
    assert start.status_code == 201, start.text
    mission_id = start.json()["mission_id"]

    response = client.get(
        f"/run-mission/{mission_id}/stream",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return mission_id, _parse_sse(response.text)


@pytest.mark.asyncio
async def test_post_missions_returns_id_quickly(client: TestClient) -> None:
    """POST /missions returns a JSON body containing `mission_id` so the BFF
    can pass it to a separate SSE consumer. The runner runs in the
    lifespan-scoped TaskGroup; the ring buffer covers the race.
    """
    response = client.post(
        "/missions",
        json={"urls": [_FIXTURE_URL]},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 201, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "mission_id" in body
    UUID(body["mission_id"])  # round-trip


@pytest.mark.asyncio
async def test_stream_replays_terminal_event_sequence(client: TestClient) -> None:
    """`POST /missions` + `GET /run-mission/{id}/stream` together replay the
    full event sequence from the ring buffer regardless of whether the
    consumer attaches before or after the runner finishes.
    """
    _, events = _post_and_stream(client, [_FIXTURE_URL])
    types = [event["type"] for event in events]
    assert types == ["task_start", "task_end", "done"]

    task_end = next(e for e in events if e["type"] == "task_end")
    assert task_end["content"]["status"] == "succeeded"
    assert _FIXTURE_MARKDOWN.startswith(task_end["content"]["preview"][:20])
    assert task_end["content"]["snapshot_key"] == _FIXTURE_SNAPSHOT_KEY

    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "succeeded"

    seqs = [event["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert seqs[0] == 0


@pytest.mark.asyncio
async def test_runner_persists_full_markdown(client: TestClient, fake_user: CurrentUser) -> None:
    mission_id, _ = _post_and_stream(client, [_FIXTURE_URL])

    _current_user.set(fake_user)
    async with transaction() as session:
        from sqlmodel import select

        rows = (await session.exec(select(Task).where(Task.mission_id == UUID(mission_id)))).all()
    assert len(rows) == 1
    task = rows[0]
    assert task.status == Status.SUCCEEDED
    assert task.parsed_markdown == _FIXTURE_MARKDOWN
    assert task.latency_ms == 42
    assert task.snapshot_key == _FIXTURE_SNAPSHOT_KEY
    assert task.snapshot_truncated is False


@pytest.mark.asyncio
async def test_stream_endpoint_404_for_unknown_mission(client: TestClient) -> None:
    """A mission id the current user does not own (or that does not exist)
    returns 404 fast — no streaming response opened.
    """
    response = client.get(
        "/run-mission/00000000-0000-0000-0000-000000000000/stream",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_missions_rejects_empty_urls(client: TestClient) -> None:
    """Pydantic enforces `1 ≤ len(urls) ≤ 20`. An empty array bounces
    with 422 before the runner is constructed.
    """
    response = client.post(
        "/missions",
        json={"urls": []},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_missions_rejects_more_than_20_urls(client: TestClient) -> None:
    response = client.post(
        "/missions",
        json={"urls": [f"https://example.com/{i}" for i in range(21)]},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 422
