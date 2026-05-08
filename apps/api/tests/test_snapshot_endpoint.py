"""`GET /missions/{id}/tasks/{task_id}/snapshot`.

Covers:
- 404 when the task is not found / cross-tenant.
- 404 when the task has no `snapshot_key`.
- 302 redirect to a freshly-generated signed URL when present.

Uses `LocalFsBlobStore.signed_url` which returns a `file://` URL — fine
for asserting the redirect contract; a browser would refuse to follow
it (the web disables the download link in dev).

DB-dependent; skips when `DATABASE_URL` is unset.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.config import settings
from app.persistence.models import MissionMode, Status, Tier
from app.persistence.repository import (
    MissionRepository,
    TaskRepository,
    UserRepository,
)
from app.security import CurrentUser, _current_user, require_user

# See test_approval_endpoint.py header — same TestClient+pytest-asyncio
# cross-loop deadlock. Tracked as a follow-up to migrate to AsyncClient.
pytestmark = [
    pytest.mark.skipif(
        settings.database_url is None,
        reason="DATABASE_URL is not set; snapshot endpoint tests need Postgres",
    ),
    pytest.mark.skip(
        reason="TestClient+pytest-asyncio cross-loop deadlock — see test_approval_endpoint.py header"
    ),
]


_FIXTURE_USER_ID = "user_test_snapshot"
_OTHER_USER_ID = "user_test_snapshot_other"
_SNAPSHOT_KEY = "user_test_snapshot/abc/snap.html.gz"


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_snap")


@pytest_asyncio.fixture
async def seed_users(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    repo = UserRepository()
    await repo.upsert(user_id=fake_user.user_id, email="snap@example.com")
    await repo.upsert(user_id=_OTHER_USER_ID, email="snap-other@example.com")


@pytest.fixture
def client(fake_user: CurrentUser, seed_users: None) -> Iterator[TestClient]:
    from app.main import app

    app.dependency_overrides[require_user] = lambda: fake_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_user, None)


@pytest.mark.asyncio
async def test_snapshot_returns_302_with_signed_url(
    client: TestClient, fake_user: CurrentUser, seed_users: None
) -> None:
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    task = await tasks_repo.create(
        mission_id=mission.id, url="https://example.com/", tier_used=Tier.HTTP
    )
    await tasks_repo.update(task.id, status=Status.SUCCEEDED, snapshot_key=_SNAPSHOT_KEY)

    response = client.get(
        f"/missions/{mission.id}/tasks/{task.id}/snapshot",
        headers={"Authorization": "Bearer fake"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"]
    # Local-fs blob store returns a `file://` URL whose path ends in the key.
    assert _SNAPSHOT_KEY in response.headers["location"]


@pytest.mark.asyncio
async def test_snapshot_404_when_no_snapshot_key(
    client: TestClient, fake_user: CurrentUser, seed_users: None
) -> None:
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    task = await tasks_repo.create(
        mission_id=mission.id, url="https://example.com/", tier_used=Tier.HTTP
    )
    # Snapshot_key never set.

    response = client.get(
        f"/missions/{mission.id}/tasks/{task.id}/snapshot",
        headers={"Authorization": "Bearer fake"},
        follow_redirects=False,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_snapshot_404_for_cross_tenant_task(client: TestClient, seed_users: None) -> None:
    """A task owned by a different user: RLS hides it → 404, same shape
    as a non-existent id."""
    other_user = CurrentUser(user_id=_OTHER_USER_ID, session_id="sess")
    _current_user.set(other_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    foreign_mission = await missions_repo.create(prompt="x", mode=MissionMode.URL)
    foreign_task = await tasks_repo.create(
        mission_id=foreign_mission.id,
        url="https://example.com/",
        tier_used=Tier.HTTP,
    )
    await tasks_repo.update(foreign_task.id, status=Status.SUCCEEDED, snapshot_key=_SNAPSHOT_KEY)

    response = client.get(
        f"/missions/{foreign_mission.id}/tasks/{foreign_task.id}/snapshot",
        headers={"Authorization": "Bearer fake"},
        follow_redirects=False,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_snapshot_404_when_task_belongs_to_different_mission(
    client: TestClient, fake_user: CurrentUser, seed_users: None
) -> None:
    """Path-id mismatch: task belongs to mission A but the URL says
    mission B. The repository scoping returns the task by id, but the
    handler asserts `task.mission_id == path mission_id` and 404s on
    mismatch.
    """
    _current_user.set(fake_user)
    missions_repo = MissionRepository()
    tasks_repo = TaskRepository()
    mission_a = await missions_repo.create(prompt="a", mode=MissionMode.URL)
    mission_b = await missions_repo.create(prompt="b", mode=MissionMode.URL)
    task = await tasks_repo.create(
        mission_id=mission_a.id, url="https://example.com/", tier_used=Tier.HTTP
    )
    await tasks_repo.update(task.id, status=Status.SUCCEEDED, snapshot_key=_SNAPSHOT_KEY)

    response = client.get(
        f"/missions/{mission_b.id}/tasks/{task.id}/snapshot",
        headers={"Authorization": "Bearer fake"},
        follow_redirects=False,
    )
    assert response.status_code == 404
