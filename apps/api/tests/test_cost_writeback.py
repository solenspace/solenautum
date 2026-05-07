"""Spec 14 — terminal cost write-back via Langfuse.

Two scenarios:
- Successful Langfuse fetch: `missions.cost_cents` carries the rolled-up
  cost in cents, the `done` SSE event content includes `cost_cents`, and
  the runner still emits the `done` terminal (invariant 5).
- Langfuse failure: `fetch_mission_cost_cents` returns `None`, the
  runner writes `cost_cents = 0`, and `done` still emits.

Hermetic: stubs the LLM chain and the agent so the runner does not
hit external services. Mocks `fetch_mission_cost_cents` directly via
monkeypatch on the `app.runner` reference (the runner imports the
helper, so patching the symbol there controls the call site).

DB-dependent; skips when `DATABASE_URL` is unset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.agent import MissionDeps, MissionResult
from app.config import settings
from app.persistence.models import MissionMode, Status, Tier
from app.persistence.repository import (
    MissionRepository,
    TaskRepository,
    UserRepository,
)
from app.runner import MissionRunner
from app.security import CurrentUser, _current_user
from app.sse import emitter
from app.tools.http import HttpScrapeOk

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; cost write-back tests need Postgres",
)


_FIXTURE_USER_ID = "user_test_cost"


@dataclass
class _FakeAgentResult:
    output: MissionResult
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


class _FakeAgent:
    async def run(self, url: str, *, model: Any, deps: MissionDeps) -> _FakeAgentResult:
        ok = HttpScrapeOk(
            url=url,
            markdown="# fixture\n",
            snapshot_key=f"{deps.user_id}/snap.gz",
            snapshot_truncated=False,
            latency_ms=10,
        )
        return _FakeAgentResult(
            output=MissionResult(
                status="ok", summary="ok", primary_url=url, markdown_excerpt=ok.markdown
            ),
            messages=[
                ModelRequest(
                    parts=[ToolReturnPart(tool_name="scrape_http", content=ok, tool_call_id="c1")]
                )
            ],
        )


class _FakeChain:
    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_cost")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="cost@example.com")


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.runner.build_agent", lambda: _FakeAgent())
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _FakeChain())


@pytest_asyncio.fixture
async def make_runner(
    fake_user: CurrentUser, seed_user: None, patch_pipeline: None
) -> MissionRunner:
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    await missions_repo.update_status(mission.id, Status.RUNNING)
    task = await tasks_repo.create(
        mission_id=mission.id, url="https://example.com/", tier_used=Tier.HTTP
    )
    return MissionRunner(user=fake_user, mission=mission, tasks=[task])


@pytest.mark.asyncio
async def test_terminal_writes_cost_cents_from_langfuse(
    make_runner: MissionRunner,
    monkeypatch: pytest.MonkeyPatch,
    fake_user: CurrentUser,
) -> None:
    async def _fake_cost(_mission_id: UUID) -> int:
        return 1  # 0.012 USD ≈ 1 cent rounded

    monkeypatch.setattr("app.runner.fetch_mission_cost_cents", _fake_cost)

    runner = make_runner
    await runner.run()

    _current_user.set(fake_user)
    fresh = await MissionRepository().get(runner._mission.id)
    assert fresh is not None
    assert fresh.cost_cents == 1


@pytest.mark.asyncio
async def test_langfuse_failure_leaves_cost_zero_and_still_emits_done(
    make_runner: MissionRunner,
    monkeypatch: pytest.MonkeyPatch,
    fake_user: CurrentUser,
) -> None:
    async def _failing_cost(_mission_id: UUID) -> int | None:
        return None  # helper swallows exceptions and returns None

    monkeypatch.setattr("app.runner.fetch_mission_cost_cents", _failing_cost)

    runner = make_runner
    await runner.run()

    _current_user.set(fake_user)
    fresh = await MissionRepository().get(runner._mission.id)
    assert fresh is not None
    assert fresh.cost_cents == 0
    # Invariant 5 — terminal `done` event must still have fired even
    # when cost fetch failed.
    state = emitter._missions.get(runner._mission.id)
    assert state is not None
    types = [payload.get("type") for _, payload in list(state.buffer)]
    assert "done" in types


@pytest.mark.asyncio
async def test_done_event_carries_cost_cents(
    make_runner: MissionRunner,
    monkeypatch: pytest.MonkeyPatch,
    fake_user: CurrentUser,
) -> None:
    async def _fake_cost(_mission_id: UUID) -> int:
        return 42

    monkeypatch.setattr("app.runner.fetch_mission_cost_cents", _fake_cost)

    runner = make_runner
    await runner.run()

    state = emitter._missions.get(runner._mission.id)
    assert state is not None
    done = next(
        (payload for _, payload in list(state.buffer) if payload.get("type") == "done"),
        None,
    )
    assert done is not None
    assert done["content"]["cost_cents"] == 42
