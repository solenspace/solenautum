"""Spec 09 — when the agent decides a mission failed (e.g. the page is
behind an unsupported WAF), the runner emits an SSE `error` event with
the matching `code` BEFORE the terminal `task_end` / `done`. The web
UI's inline error chip reads that code.

Hermetic: stubs the LLM chain (no real model call) and the HTTP fetcher
(returns Akamai-fingerprint headers so the HTTP tier surfaces
`reason=site_not_supported`). The fake agent forwards the tool result's
reason into a `MissionResult(status="error", error_code="site_not_supported")`.

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
from app.tools.http import HttpScrapeArgs, HttpScrapeFailure, HttpToolDeps

# See test_approval_endpoint.py header — same TestClient+pytest-asyncio
# cross-loop deadlock. Tracked as a follow-up to migrate to AsyncClient.
pytestmark = [
    pytest.mark.skipif(
        settings.database_url is None,
        reason="DATABASE_URL is not set; runner error-propagation needs Postgres",
    ),
    pytest.mark.skip(
        reason="TestClient+pytest-asyncio cross-loop deadlock — see test_approval_endpoint.py header"
    ),
]


_FIXTURE_USER_ID = "user_test_err"
_FIXTURE_URL = "https://example.com/akamai-fronted"


@dataclass
class _FakeAgentResult:
    output: MissionResult
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


class _FakeAgent:
    """Calls the (stubbed) HTTP tool once. The tool returns
    `HttpScrapeFailure(reason="site_not_supported")` because the fake
    upstream returns Akamai headers. The agent then emits a terminal
    `MissionResult(status="error", error_code="site_not_supported")` —
    matching the system-prompt rules verbatim.
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
        assert isinstance(tool_result, HttpScrapeFailure)
        assert tool_result.reason == "site_not_supported"

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
                status="error",
                summary="Page is behind an unsupported WAF.",
                error_code="site_not_supported",
                detected_protections=tool_result.detected_protections,
            ),
            messages=[message],
        )


class _FakePage:
    def __init__(self, *, url: str, status: int, headers: dict[str, str], body: str = "") -> None:
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body


class _FakeChain:
    """Replaces `LLMProviderChain` so the route test does not depend on
    LLM env credentials. Just runs the callable with a sentinel model.
    """

    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_err")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="err@example.com")


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get(url: str, **_kw: Any) -> _FakePage:
        return _FakePage(
            url=url,
            status=403,
            headers={"server": "AkamaiGHost"},
            body="",
        )

    async def _allow_all(url: str, *, robots_override: bool = False) -> None:
        return None

    monkeypatch.setattr("app.tools.http.AsyncFetcher.get", _fake_get)
    monkeypatch.setattr("app.tools.http.assert_robots_allows", _allow_all)
    monkeypatch.setattr("app.runner.build_agent", lambda: _FakeAgent())
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
        lines: dict[str, str] = {}
        for line in block.split("\n"):
            if ":" in line and not line.startswith(":"):
                name, _, value = line.partition(": ")
                lines[name] = value
        if "data" in lines:
            events.append(json.loads(lines["data"]))
    return events


def _post_and_stream(client: TestClient, urls: list[str]) -> tuple[str, list[dict[str, Any]]]:
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
    return mission_id, _parse_sse(response.text)


@pytest.mark.asyncio
async def test_runner_emits_error_before_terminal_events(client: TestClient) -> None:
    _, events = _post_and_stream(client, [_FIXTURE_URL])
    types = [e["type"] for e in events]

    # error → task_end → done, in that order, after task_start
    assert types == ["task_start", "error", "task_end", "done"]

    error_event = next(e for e in events if e["type"] == "error")
    assert error_event["content"]["code"] == "site_not_supported"
    assert error_event["content"]["detected_protections"] == ["akamai"]

    task_end = next(e for e in events if e["type"] == "task_end")
    assert task_end["content"]["status"] == "failed"

    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "failed"


@pytest.mark.asyncio
async def test_runner_marks_task_failed_in_db(client: TestClient, fake_user: CurrentUser) -> None:
    mission_id, _ = _post_and_stream(client, [_FIXTURE_URL])

    _current_user.set(fake_user)
    async with transaction() as session:
        from sqlmodel import select

        rows = (await session.exec(select(Task).where(Task.mission_id == UUID(mission_id)))).all()
    assert len(rows) == 1
    task = rows[0]
    assert task.status == Status.FAILED
    # No successful tool call → no snapshot key, no parsed markdown
    assert task.snapshot_key is None
    assert task.parsed_markdown is None
