"""End-to-end test of `run_description_mission`: the discovery agent and
LLM chain are stubbed; the real `MissionRunner` runs against stubbed tier
tools so we exercise the full state machine (discovering →
awaiting_approval → scraping → done) plus the cancellation and timeout
paths.

DB-dependent (mission/task row writes); skips when `DATABASE_URL` is
unset.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.agent import DiscoveryDeps, DiscoveryMissionResult, MissionDeps, MissionResult
from app.config import settings
from app.persistence.models import MissionMode, MissionPhase, Status
from app.persistence.repository import (
    MissionRepository,
    UserRepository,
)
from app.runner import (
    run_description_mission,
    submit_approval,
)
from app.search import DiscoveredUrl
from app.security import CurrentUser, _current_user
from app.sse import emitter
from app.tools.http import HttpScrapeOk

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; description runner tests need Postgres",
)


_FIXTURE_USER_ID = "user_test_description"


@dataclass
class _FakeAgentResult:
    output: Any
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


@dataclass
class _FakeDiscoveryAgent:
    """Stub that returns a pre-built `DiscoveryMissionResult` so the test
    doesn't need a real LLM. Exposes `.run()` matching pydantic-ai's
    signature (`prompt`, `model=...`, `deps=...`).
    """

    result: DiscoveryMissionResult

    async def run(self, prompt: str, *, model: Any, deps: DiscoveryDeps) -> _FakeAgentResult:
        return _FakeAgentResult(output=self.result)


@dataclass
class _FakeScrapeAgent:
    """Stub for the inner `MissionRunner`'s scrape agent. Returns a
    successful `MissionResult` and a tool-call history that
    `last_ok_tool_call` can walk.
    """

    async def run(self, url: str, *, model: Any, deps: MissionDeps) -> _FakeAgentResult:
        ok = HttpScrapeOk(
            url=url,
            markdown="# fixture\n",
            snapshot_key=f"{deps.user_id}/snap.gz",
            snapshot_truncated=False,
            latency_ms=10,
        )
        message = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="scrape_http",
                    content=ok,
                    tool_call_id="call_1",
                ),
            ],
        )
        return _FakeAgentResult(
            output=MissionResult(
                status="ok",
                summary="ok",
                primary_url=url,
                markdown_excerpt="# fixture",
            ),
            messages=[message],
        )


class _FakeChain:
    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_descr")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="descr@example.com")


@pytest_asyncio.fixture
async def seeded_mission(fake_user: CurrentUser, seed_user: None) -> Any:
    """Create a fresh description-mode mission row owned by the fake user.
    Each test gets its own mission_id so emitter state is isolated.
    """
    _current_user.set(fake_user)
    mission = await MissionRepository().create(
        prompt="popular AI agent frameworks 2026",
        mode=MissionMode.DESCRIPTION,
        skip_approval=False,
    )
    yield mission
    emitter._missions.pop(mission.id, None)


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    discovery: DiscoveryMissionResult,
) -> None:
    monkeypatch.setattr(
        "app.runner.build_discovery_agent",
        lambda: _FakeDiscoveryAgent(result=discovery),
    )
    monkeypatch.setattr(
        "app.runner.build_agent",
        lambda: _FakeScrapeAgent(),
    )
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _FakeChain())


def _events(mission_id: UUID) -> list[dict[str, Any]]:
    state = emitter._missions.get(mission_id)
    return [payload for _, payload in state.buffer] if state is not None else []


@pytest.mark.asyncio
async def test_skip_approval_path_runs_to_done(
    fake_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    seed_user: None,
) -> None:
    """`skip_approval=true` jumps from discovery directly into scraping."""
    discovery = DiscoveryMissionResult(
        status="ok",
        urls=[
            DiscoveredUrl(url="https://example.com/a", score=0.9, source="tavily"),
            DiscoveredUrl(url="https://example.com/b", score=0.7, source="tavily"),
        ],
    )
    _patch_pipeline(monkeypatch, discovery=discovery)

    _current_user.set(fake_user)
    mission = await MissionRepository().create(
        prompt="x",
        mode=MissionMode.DESCRIPTION,
        skip_approval=True,
    )

    try:
        await run_description_mission(
            user=fake_user, mission=mission, query="x", approval_timeout_s=5.0
        )

        events = _events(mission.id)
        types = [e["type"] for e in events]
        assert types[:2] == ["url_discovered", "url_discovered"]
        # discovery_complete arrives with awaiting_approval=False
        dc = next(e for e in events if e["type"] == "discovery_complete")
        assert dc["content"]["awaiting_approval"] is False
        assert dc["content"]["count"] == 2
        # The inner MissionRunner emits task_start / task_end for both URLs.
        task_starts = [e for e in events if e["type"] == "task_start"]
        task_ends = [e for e in events if e["type"] == "task_end"]
        assert len(task_starts) == 2
        assert len(task_ends) == 2
        # Mission terminates with done(succeeded).
        done = next(e for e in events if e["type"] == "done")
        assert done["content"]["mission_status"] == "succeeded"

        _current_user.set(fake_user)
        fresh = await MissionRepository().get(mission.id)
        assert fresh is not None
        assert fresh.phase == MissionPhase.DONE
        assert fresh.status == Status.SUCCEEDED
        assert fresh.approved_urls == [
            "https://example.com/a",
            "https://example.com/b",
        ]
    finally:
        emitter._missions.pop(mission.id, None)


@pytest.mark.asyncio
async def test_approval_gate_resumes_with_subset(
    fake_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    seeded_mission: Any,
) -> None:
    """The runner parks on the approval gate; `submit_approval` unparks
    with the user's chosen subset; scraping proceeds.
    """
    discovery = DiscoveryMissionResult(
        status="ok",
        urls=[
            DiscoveredUrl(url="https://example.com/a", score=0.9, source="tavily"),
            DiscoveredUrl(url="https://example.com/b", score=0.6, source="tavily"),
            DiscoveredUrl(url="https://example.com/c", score=0.3, source="tavily"),
        ],
    )
    _patch_pipeline(monkeypatch, discovery=discovery)

    runner_task = asyncio.create_task(
        run_description_mission(
            user=fake_user,
            mission=seeded_mission,
            query="x",
            approval_timeout_s=5.0,
        )
    )

    # Wait until the runner emits `discovery_complete` and parks. Polling
    # the buffer is the cheapest signal — `submit_approval` before the
    # registry is populated returns `no_pending`.
    deadline = asyncio.get_event_loop().time() + 5.0
    while asyncio.get_event_loop().time() < deadline:
        types = [e["type"] for e in _events(seeded_mission.id)]
        if "discovery_complete" in types:
            break
        await asyncio.sleep(0.02)
    assert "discovery_complete" in [e["type"] for e in _events(seeded_mission.id)]

    outcome = submit_approval(
        seeded_mission.id,
        approved_urls=["https://example.com/a", "https://example.com/b"],
        skip_approval=False,
    )
    assert outcome == "accepted"

    await asyncio.wait_for(runner_task, timeout=10.0)

    events = _events(seeded_mission.id)
    task_starts = [e for e in events if e["type"] == "task_start"]
    assert len(task_starts) == 2
    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "succeeded"

    _current_user.set(fake_user)
    fresh = await MissionRepository().get(seeded_mission.id)
    assert fresh is not None
    assert fresh.approved_urls == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert fresh.phase == MissionPhase.DONE


@pytest.mark.asyncio
async def test_approval_timeout_cancels_mission(
    fake_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    seeded_mission: Any,
) -> None:
    """No approval within the bounded timeout → `done(cancelled)` and
    mission status flips to CANCELLED.
    """
    discovery = DiscoveryMissionResult(
        status="ok",
        urls=[
            DiscoveredUrl(url="https://example.com/a", score=0.9, source="tavily"),
        ],
    )
    _patch_pipeline(monkeypatch, discovery=discovery)

    await run_description_mission(
        user=fake_user,
        mission=seeded_mission,
        query="x",
        approval_timeout_s=0.05,
    )

    events = _events(seeded_mission.id)
    types = [e["type"] for e in events]
    assert "discovery_complete" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "cancelled"

    _current_user.set(fake_user)
    fresh = await MissionRepository().get(seeded_mission.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED


@pytest.mark.asyncio
async def test_discovery_error_emits_error_then_done(
    fake_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    seeded_mission: Any,
) -> None:
    discovery = DiscoveryMissionResult(
        status="error",
        urls=[],
        error_code="rate_limited",
        error_message="upstream rate limited",
    )
    _patch_pipeline(monkeypatch, discovery=discovery)

    await run_description_mission(
        user=fake_user,
        mission=seeded_mission,
        query="x",
        approval_timeout_s=5.0,
    )

    events = _events(seeded_mission.id)
    types = [e["type"] for e in events]
    assert "error" in types
    err = next(e for e in events if e["type"] == "error")
    assert err["content"]["code"] == "rate_limited"
    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "failed"


@pytest.mark.asyncio
async def test_chain_failure_emits_terminal_done(
    fake_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
    seeded_mission: Any,
) -> None:
    """If the LLM chain raises (both providers exhausted), the runner still
    emits a terminal `done(failed)` so the slide-over does not hang.
    Invariant 5 at the mission level.
    """

    class _FailingChain:
        async def with_fallback(self, run: Any) -> Any:
            raise RuntimeError("openrouter and groq both 5xx'd")

    monkeypatch.setattr(
        "app.runner.build_discovery_agent",
        lambda: _FakeDiscoveryAgent(result=DiscoveryMissionResult(status="ok")),
    )
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _FailingChain())

    await run_description_mission(
        user=fake_user,
        mission=seeded_mission,
        query="x",
        approval_timeout_s=5.0,
    )

    events = _events(seeded_mission.id)
    types = [e["type"] for e in events]
    assert "error" in types
    err = next(e for e in events if e["type"] == "error")
    assert err["content"]["code"] == "discovery_failed"
    done = next(e for e in events if e["type"] == "done")
    assert done["content"]["mission_status"] == "failed"
