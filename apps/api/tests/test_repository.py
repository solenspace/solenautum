from __future__ import annotations

import pytest
import pytest_asyncio

from app.config import settings
from app.persistence.db import transaction
from app.persistence.models import MissionMode, Status, Task, Tier
from app.persistence.repository import (
    MissionRepository,
    TaskRepository,
    UserRepository,
)
from app.security import CurrentUser, _current_user

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; persistence-layer tests need a real Postgres",
)


@pytest.fixture
def user_a() -> CurrentUser:
    return CurrentUser(user_id="user_test_a", session_id="sess_a")


@pytest.fixture
def user_b() -> CurrentUser:
    return CurrentUser(user_id="user_test_b", session_id="sess_b")


@pytest_asyncio.fixture(autouse=True)
async def seed_users(user_a: CurrentUser, user_b: CurrentUser):
    """Seed both test users (no RLS on the users table)."""
    _current_user.set(None)
    repo = UserRepository()
    await repo.upsert(user_id=user_a.user_id, email="a@example.com")
    await repo.upsert(user_id=user_b.user_id, email="b@example.com")
    yield
    _current_user.set(None)


@pytest.mark.asyncio
async def test_creates_and_reads_own_mission(user_a: CurrentUser):
    _current_user.set(user_a)
    repo = MissionRepository()
    mission = await repo.create(prompt="hello", mode=MissionMode.URL)
    fetched = await repo.get(mission.id)
    assert fetched is not None
    assert fetched.user_id == user_a.user_id
    assert fetched.status == Status.PENDING


@pytest.mark.asyncio
async def test_rls_blocks_cross_tenant_read(user_a: CurrentUser, user_b: CurrentUser):
    _current_user.set(user_a)
    repo = MissionRepository()
    mission = await repo.create(prompt="A's data", mode=MissionMode.URL)

    _current_user.set(user_b)
    fetched = await repo.get(mission.id)
    assert fetched is None  # RLS hides the row from user_b


@pytest.mark.asyncio
async def test_task_inherits_rls_via_mission(user_a: CurrentUser, user_b: CurrentUser):
    _current_user.set(user_a)
    mission_repo = MissionRepository()
    task_repo = TaskRepository()
    mission = await mission_repo.create(prompt="t", mode=MissionMode.URL)
    task = await task_repo.create(
        mission_id=mission.id,
        url="https://example.com/",
        tier_used=Tier.HTTP,
    )

    # As user_b, the task is invisible — the update is a silent no-op
    # (RLS hides the row before SELECT FOR UPDATE can grab it).
    _current_user.set(user_b)
    await task_repo.update(task.id, status=Status.SUCCEEDED)

    # Re-fetch as user_a; the task's status is still PENDING, proving
    # user_b's update was hidden, not applied.
    _current_user.set(user_a)
    async with transaction() as session:
        refetched = await session.get(Task, task.id)
    assert refetched is not None
    assert refetched.status == Status.PENDING
