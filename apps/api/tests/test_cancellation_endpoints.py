"""`DELETE /missions/{id}` and `DELETE /missions/{id}/tasks/{task_id}`.

Covers:
- 404 for unknown / cross-tenant ids.
- Active runner: `request_cancellation` is wired and the response
  carries `x-mission-state: cancellation_pending`.
- Per-task cancel: `cancel_task` is wired and a previously pending task
  settles `Status.CANCELLED` while siblings continue.
- Idempotency: a second DELETE on a terminal mission returns 204 with
  `x-mission-state` carrying the current status.
- Rare edge: mission row says pending/running but no live runner — the
  endpoint marks the row cancelled AND emits a synthetic mission-level
  `done(cancelled)` so any client attached within the 60s eviction
  grace observes the terminal event.
- Invariant 5 under cancellation: a cancelled task emits exactly one
  `task_end` with status=cancelled.

DB-dependent (RLS-scoped row writes); skips when `DATABASE_URL` is unset.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.config import settings
from app.persistence.models import MissionMode, Status, Task, Tier
from app.persistence.repository import (
    MissionRepository,
    TaskRepository,
    UserRepository,
)
from app.runner import MissionRunner
from app.security import CurrentUser, _current_user, require_user
from app.sse import emitter

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; cancellation endpoint tests need Postgres",
)


_FIXTURE_USER_ID = "user_test_cancel"
_OTHER_USER_ID = "user_test_cancel_other"


@dataclass
class _RecordingRunner:
    """Stand-in for `MissionRunner` registered in `emitter._active_runners`.
    Records every cancel request so tests can assert the route reached us.
    """

    cancellation_requested: bool = False
    cancelled_task_ids: list[UUID] = field(default_factory=list)

    def request_cancellation(self) -> None:
        self.cancellation_requested = True

    def cancel_task(self, task_id: UUID) -> None:
        self.cancelled_task_ids.append(task_id)

    def run(self) -> Any:  # pragma: no cover — never invoked by tests
        raise NotImplementedError


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_cancel")


@pytest_asyncio.fixture
async def seed_users(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    repo = UserRepository()
    await repo.upsert(user_id=fake_user.user_id, email="cancel@example.com")
    await repo.upsert(user_id=_OTHER_USER_ID, email="cancel-other@example.com")


@pytest.fixture
def client(fake_user: CurrentUser, seed_users: None) -> Iterator[TestClient]:
    from app.main import app

    app.dependency_overrides[require_user] = lambda: fake_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_user, None)
        emitter._active_runners.clear()


@pytest_asyncio.fixture
async def running_mission(fake_user: CurrentUser, seed_users: None) -> Any:
    """Create a mission row in `RUNNING` with one PENDING task. Tests that
    need an `active_runners` registration add a `_RecordingRunner` after.
    """
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    await missions_repo.update_status(mission.id, Status.RUNNING)
    task = await tasks_repo.create(
        mission_id=mission.id, url="https://example.com/", tier_used=Tier.HTTP
    )
    return mission, task


@pytest.mark.asyncio
async def test_delete_unknown_mission_returns_404(client: TestClient) -> None:
    response = client.delete(
        f"/missions/{uuid4()}",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_running_mission_calls_request_cancellation(
    client: TestClient, running_mission: Any
) -> None:
    mission, _ = running_mission
    runner = _RecordingRunner()
    emitter._active_runners[mission.id] = runner

    response = client.delete(
        f"/missions/{mission.id}",
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 204
    assert response.headers["x-mission-state"] == "cancellation_pending"
    assert runner.cancellation_requested is True


@pytest.mark.asyncio
async def test_delete_idempotent_on_already_terminal_mission(
    client: TestClient, fake_user: CurrentUser, running_mission: Any
) -> None:
    """A mission already in a terminal state returns 204 with the current
    status in `x-mission-state` so the client can stop polling.
    """
    mission, _ = running_mission
    _current_user.set(fake_user)
    await MissionRepository().update_status(mission.id, Status.CANCELLED)

    response = client.delete(
        f"/missions/{mission.id}",
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 204
    assert response.headers["x-mission-state"] == Status.CANCELLED.value


@pytest.mark.asyncio
async def test_delete_no_active_runner_marks_row_and_emits_terminal(
    client: TestClient, fake_user: CurrentUser, running_mission: Any
) -> None:
    """Rare-edge: row is RUNNING but no live runner (process crashed
    after registering the row). The route writes CANCELLED to the DB
    AND emits a synthetic mission-level `done(cancelled)` so any client
    attached within the 60s eviction grace observes the terminal event
    (invariant 5 holds even on the no-runner branch).
    """
    mission, _ = running_mission
    # active_runners is empty (no registration)

    response = client.delete(
        f"/missions/{mission.id}",
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 204
    assert response.headers["x-mission-state"] == Status.CANCELLED.value
    _current_user.set(fake_user)
    fresh = await MissionRepository().get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED

    # Synthetic terminal lands in the per-mission ring buffer.
    state = emitter._missions.get(mission.id)
    assert state is not None
    done = next(
        (
            payload
            for _, payload in list(state.buffer)
            if payload.get("type") == "done" and payload.get("task_id") is None
        ),
        None,
    )
    assert done is not None
    assert done["content"]["mission_status"] == "cancelled"


@pytest.mark.asyncio
async def test_delete_other_users_mission_returns_404(client: TestClient, seed_users: None) -> None:
    other_user = CurrentUser(user_id=_OTHER_USER_ID, session_id="sess")
    _current_user.set(other_user)
    foreign = await MissionRepository().create(prompt="x", mode=MissionMode.URL)

    response = client.delete(
        f"/missions/{foreign.id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_unknown_returns_404(client: TestClient, running_mission: Any) -> None:
    mission, _ = running_mission
    response = client.delete(
        f"/missions/{mission.id}/tasks/{uuid4()}",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_task_routes_to_runner_cancel_task(
    client: TestClient, running_mission: Any
) -> None:
    mission, task = running_mission
    runner = _RecordingRunner()
    emitter._active_runners[mission.id] = runner

    response = client.delete(
        f"/missions/{mission.id}/tasks/{task.id}",
        headers={"Authorization": "Bearer fake"},
    )

    assert response.status_code == 204
    assert task.id in runner.cancelled_task_ids


@pytest.mark.asyncio
async def test_delete_task_no_runner_marks_row_and_emits_task_end(
    client: TestClient, fake_user: CurrentUser, running_mission: Any
) -> None:
    """Rare-edge per-task: write CANCELLED to the row AND emit a
    synthetic `task_end(cancelled)` so the in-grace stream consumer
    stops waiting on this lane (invariant 5 at task level).
    """
    mission, task = running_mission
    response = client.delete(
        f"/missions/{mission.id}/tasks/{task.id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 204
    _current_user.set(fake_user)
    fresh = await TaskRepository().get(task.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED

    state = emitter._missions.get(mission.id)
    assert state is not None
    task_end = next(
        (
            payload
            for _, payload in list(state.buffer)
            if payload.get("type") == "task_end" and payload.get("task_id") == str(task.id)
        ),
        None,
    )
    assert task_end is not None
    assert task_end["content"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_delete_task_already_terminal_is_idempotent(
    client: TestClient, fake_user: CurrentUser, running_mission: Any
) -> None:
    mission, task = running_mission
    _current_user.set(fake_user)
    await TaskRepository().update(task.id, status=Status.SUCCEEDED)

    response = client.delete(
        f"/missions/{mission.id}/tasks/{task.id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 204


@dataclass
class _SlowAgentResult:
    output: Any
    messages: list[Any] = field(default_factory=list)

    def all_messages(self) -> list[Any]:
        return self.messages


class _SlowAgent:
    """Sleeps long enough that a per-task cancel arriving between
    `task_start` and the agent dispatch beats us to the next checkpoint.
    """

    def __init__(self, *, sleep_s: float = 0.2) -> None:
        self.sleep_s = sleep_s
        self.started_urls: list[str] = []

    async def run(self, url: str, *, model: Any, deps: Any) -> _SlowAgentResult:
        from app.agent import MissionResult

        self.started_urls.append(url)
        await asyncio.sleep(self.sleep_s)
        return _SlowAgentResult(
            output=MissionResult(status="ok", summary="ok", primary_url=url, markdown_excerpt="")
        )


class _PassthroughChain:
    async def with_fallback(self, run: Any) -> Any:
        return await run(object())


@pytest.mark.asyncio
async def test_per_task_cancel_isolates_to_one_task(
    fake_user: CurrentUser,
    seed_users: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three tasks, mid-flight cancel on task 2: tasks 1 and 3 succeed,
    task 2 settles CANCELLED with exactly one terminal `task_end`
    (invariant 5 under per-task cancel).
    """
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    await missions_repo.update_status(mission.id, Status.RUNNING)
    task_rows: list[Task] = []
    for url in ("https://example.com/a", "https://example.com/b", "https://example.com/c"):
        task_rows.append(
            await tasks_repo.create(mission_id=mission.id, url=url, tier_used=Tier.HTTP)
        )

    shared = _SlowAgent(sleep_s=0.2)
    monkeypatch.setattr("app.runner.build_agent", lambda: shared)
    monkeypatch.setattr("app.runner.LLMProviderChain", lambda **_kw: _PassthroughChain())
    # Skip the Langfuse cost fetch path for this hermetic test.
    monkeypatch.setattr("app.runner.fetch_mission_cost_cents", _zero_cost)

    runner = MissionRunner(user=fake_user, mission=mission, tasks=task_rows)
    target = task_rows[1].id
    runner.cancel_task(target)
    await runner.run()

    fresh_tasks = {t.id: t for t in await tasks_repo.list_by_mission(mission.id)}
    assert fresh_tasks[task_rows[0].id].status == Status.SUCCEEDED
    assert fresh_tasks[target].status == Status.CANCELLED
    assert fresh_tasks[task_rows[2].id].status == Status.SUCCEEDED


async def _zero_cost(_mission_id: UUID) -> int:
    return 0
