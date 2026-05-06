"""Spec 10 — `MissionRunner` runs N tasks under one TaskGroup.

Three concerns:
- Concurrency: all tasks start within ~50ms of each other (no serial
  per-task fan-out).
- Cancellation: `request_cancellation()` set before `run()` causes every
  task to settle as `CANCELLED`; no task is `FAILED`.
- Structured concurrency: after `runner.run()` returns, no detached
  tasks remain (invariant 3).

Hermetic: stubs the LLM chain and the HTTP fetcher; uses a fake agent
whose `.run()` records its start timestamp so the concurrency assertion
is deterministic. DB-dependent (RLS-scoped row writes), skips when
`DATABASE_URL` is unset.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import pytest
import pytest_asyncio
from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.agent import MissionDeps, MissionResult
from app.config import settings
from app.persistence.models import MissionMode, Status, Task, Tier
from app.persistence.repository import (
    MissionRepository,
    TaskRepository,
    UserRepository,
)
from app.runner import MissionRunner
from app.security import CurrentUser, _current_user
from app.tools.http import HttpScrapeOk

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; runner taskgroup tests need Postgres",
)

_FIXTURE_USER_ID = "user_test_taskgroup"
_FIXTURE_URLS = [
    "https://example.com/a",
    "https://example.com/b",
    "https://example.com/c",
    "https://example.com/d",
    "https://example.com/e",
]


@dataclass
class _FakeAgentResult:
    output: MissionResult
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


@dataclass
class _FakeAgent:
    """Records the wall-clock start timestamp of every `.run()` call so
    the test can assert that all five tasks actually ran in parallel,
    not serially.
    """

    start_times: list[float] = field(default_factory=list)
    sleep_seconds: float = 0.05

    async def run(self, url: str, *, model: Any, deps: MissionDeps) -> _FakeAgentResult:
        self.start_times.append(perf_counter())
        await asyncio.sleep(self.sleep_seconds)
        ok = HttpScrapeOk(
            url=url,
            markdown="# fixture\n",
            snapshot_key=f"{deps.user_id}/snap.gz",
            snapshot_truncated=False,
            latency_ms=10,
        )
        return _FakeAgentResult(
            output=MissionResult(
                status="ok",
                summary="ok",
                primary_url=url,
                markdown_excerpt=ok.markdown[:500],
            ),
            messages=[
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="scrape_http",
                            content=ok,
                            tool_call_id="call_1",
                        ),
                    ],
                ),
            ],
        )


class _FakeChain:
    """Replaces `LLMProviderChain` so the test does not need OPENROUTER /
    GROQ env credentials. Just runs the callable with a sentinel model.
    """

    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_taskgroup")


@pytest_asyncio.fixture
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="tg@example.com")


@pytest.fixture
def fake_agent_holder() -> list[_FakeAgent]:
    return []


@pytest.fixture
def patch_pipeline(monkeypatch: pytest.MonkeyPatch, fake_agent_holder: list[_FakeAgent]) -> None:
    """Replace `build_agent` and `LLMProviderChain` so each test runs
    deterministically without external services.

    All `_run_task` invocations share one `_FakeAgent` instance per
    test so the test can read `start_times` after `runner.run()`.
    """
    shared = _FakeAgent()
    fake_agent_holder.append(shared)

    monkeypatch.setattr("app.runner.build_agent", lambda: shared)
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _FakeChain())


@pytest_asyncio.fixture
async def make_runner(
    fake_user: CurrentUser, seed_user: None, patch_pipeline: None
) -> MissionRunner:
    """Persist one mission with five PENDING task rows and return a
    runner ready to call `run()` on.
    """
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()

    mission = await missions_repo.create(prompt="\n".join(_FIXTURE_URLS), mode=MissionMode.URL)
    await missions_repo.update_status(mission.id, Status.RUNNING)

    rows: list[Task] = []
    for url in _FIXTURE_URLS:
        rows.append(
            await tasks_repo.create(mission_id=mission.id, url=url, tier_used=Tier.HTTP),
        )
    return MissionRunner(user=fake_user, mission=mission, tasks=rows)


@pytest.mark.asyncio
async def test_all_tasks_run_concurrently(
    make_runner: MissionRunner, fake_agent_holder: list[_FakeAgent]
) -> None:
    """Five fake `agent.run()` calls should all start within ~50ms of
    each other when spawned by the same TaskGroup. Serial fan-out would
    spread the start times by `5 * sleep_seconds`.
    """
    runner = make_runner
    await runner.run()

    fake_agent = fake_agent_holder[0]
    assert len(fake_agent.start_times) == 5
    spread = max(fake_agent.start_times) - min(fake_agent.start_times)
    assert spread < 0.05, f"task start times spread by {spread:.3f}s — not concurrent"


@pytest.mark.asyncio
async def test_cancellation_before_run_marks_all_tasks_cancelled(
    make_runner: MissionRunner, fake_user: CurrentUser
) -> None:
    """Setting the cancellation event before `run()` causes every task
    to bail at the entry check with `Status.CANCELLED`. None should
    surface as `FAILED`.
    """
    runner = make_runner
    runner.request_cancellation()
    await runner.run()

    _current_user.set(fake_user)
    tasks = await TaskRepository().list_by_mission(runner._mission.id)
    statuses = {t.status for t in tasks}
    assert statuses == {Status.CANCELLED}, f"unexpected statuses: {statuses}"

    fresh_mission = await MissionRepository().get(runner._mission.id)
    assert fresh_mission is not None
    assert fresh_mission.status == Status.CANCELLED


@pytest.mark.asyncio
async def test_no_detached_tasks_after_run(make_runner: MissionRunner) -> None:
    """Invariant 3 — after `runner.run()` returns, no per-task
    coroutine remains alive in the loop. The TaskGroup awaits every
    child on exit; nothing else spawns work.
    """
    before = {task for task in asyncio.all_tasks() if not task.done()}
    runner = make_runner
    await runner.run()
    after = {task for task in asyncio.all_tasks() if not task.done()}

    leaked = after - before
    assert not leaked, f"runner leaked {len(leaked)} task(s): {leaked!r}"


@pytest.mark.asyncio
async def test_request_cancellation_sets_event(make_runner: MissionRunner) -> None:
    """The `request_cancellation()` mechanic flips the internal Event;
    Spec 14 will plug a user-facing endpoint into this method.
    """
    runner = make_runner
    assert not runner._cancellation_requested.is_set()
    runner.request_cancellation()
    assert runner._cancellation_requested.is_set()
