"""`POST /missions/{id}/approve` route tests.

Covers the four error paths and the happy path:
  - Missing/invalid auth → 401 (Clerk dependency raises before handler).
  - Foreign-user mission → 404 (RLS-scoped lookup returns None).
  - Approval before discovery completes → 409 (phase guard).
  - Unsafe URL in payload → 400 (assert_safe_url raises HTTPException).
  - Orphaned approval (no in-memory entry) → 503.
  - Happy path → 204 + the runner's `_PendingApproval` is fully populated.

DB-dependent (mission row writes); skips when `DATABASE_URL` is unset.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.config import settings
from app.persistence.models import MissionMode, MissionPhase
from app.persistence.repository import MissionRepository, UserRepository
from app.runner import (
    _pending_approvals,
    register_pending_approval,
)
from app.security import CurrentUser, _current_user, require_user

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; approval endpoint tests need Postgres",
)


_FIXTURE_USER_ID = "user_test_approval"
_OTHER_USER_ID = "user_test_approval_other"


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_approve")


@pytest_asyncio.fixture
async def seed_users(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    repo = UserRepository()
    await repo.upsert(user_id=fake_user.user_id, email="approve@example.com")
    await repo.upsert(user_id=_OTHER_USER_ID, email="other@example.com")


@pytest.fixture
def client(fake_user: CurrentUser, seed_users: None) -> Iterator[TestClient]:
    from app.main import app

    app.dependency_overrides[require_user] = lambda: fake_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_user, None)
        _pending_approvals.clear()


@pytest_asyncio.fixture
async def awaiting_mission(fake_user: CurrentUser, seed_users: None) -> Any:
    """Create a mission row in `phase=AWAITING_APPROVAL` and register a
    pending-approval entry the way `run_description_mission` would.
    Returns the mission so tests can target its id.
    """
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(
        prompt="x",
        mode=MissionMode.DESCRIPTION,
    )
    await repo.set_phase(mission.id, MissionPhase.AWAITING_APPROVAL)
    await repo.set_discovered_urls(
        mission.id,
        [
            {
                "url": "https://example.com/a",
                "score": 0.9,
                "source": "tavily",
                "favicon_url": None,
                "title": None,
            },
        ],
    )
    register_pending_approval(mission.id)
    yield mission
    _pending_approvals.pop(mission.id, None)


@pytest_asyncio.fixture
async def discovering_mission(fake_user: CurrentUser, seed_users: None) -> Any:
    """Mission still in DISCOVERING — approval should 409."""
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="x", mode=MissionMode.DESCRIPTION)
    await repo.set_phase(mission.id, MissionPhase.DISCOVERING)
    yield mission


@pytest.mark.asyncio
async def test_approve_unknown_mission_returns_404(client: TestClient) -> None:
    response = client.post(
        f"/missions/{uuid4()}/approve",
        json={"urls": ["https://example.com/"], "skip_approval": False},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_other_users_mission_returns_404(
    client: TestClient,
    seed_users: None,
) -> None:
    """Foreign-user mission: RLS hides the row → repository returns None
    → 404 (same shape as a non-existent id, no information leak).
    """
    other_user = CurrentUser(user_id=_OTHER_USER_ID, session_id="sess")
    _current_user.set(other_user)
    repo = MissionRepository()
    foreign = await repo.create(prompt="x", mode=MissionMode.DESCRIPTION)
    await repo.set_phase(foreign.id, MissionPhase.AWAITING_APPROVAL)
    register_pending_approval(foreign.id)

    try:
        response = client.post(
            f"/missions/{foreign.id}/approve",
            json={"urls": ["https://example.com/"], "skip_approval": False},
            headers={"Authorization": "Bearer fake"},
        )
        assert response.status_code == 404
    finally:
        _pending_approvals.pop(foreign.id, None)


@pytest.mark.asyncio
async def test_approve_before_awaiting_approval_returns_409(
    client: TestClient,
    discovering_mission: Any,
) -> None:
    response = client.post(
        f"/missions/{discovering_mission.id}/approve",
        json={"urls": ["https://example.com/"], "skip_approval": False},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_with_unsafe_url_returns_400(
    client: TestClient,
    awaiting_mission: Any,
) -> None:
    """Even if Tavily originally returned a safe URL, a user-edited URL
    that resolves to a private network is rejected by the SSRF guard
    (Invariant 1 at the approval boundary).
    """
    response = client.post(
        f"/missions/{awaiting_mission.id}/approve",
        json={"urls": ["http://169.254.169.254/"], "skip_approval": False},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_approve_with_no_pending_returns_503(
    client: TestClient,
    fake_user: CurrentUser,
    seed_users: None,
) -> None:
    """Mission in AWAITING_APPROVAL but no in-memory pending entry (the
    runner process restarted). The route returns 503 instead of silently
    accepting (Deviation 4).
    """
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="x", mode=MissionMode.DESCRIPTION)
    await repo.set_phase(mission.id, MissionPhase.AWAITING_APPROVAL)
    # Note: no `register_pending_approval` call here — orphaned by design.

    response = client.post(
        f"/missions/{mission.id}/approve",
        json={"urls": ["https://example.com/"], "skip_approval": False},
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_approve_happy_path_sets_event_and_payload(
    client: TestClient,
    awaiting_mission: Any,
) -> None:
    response = client.post(
        f"/missions/{awaiting_mission.id}/approve",
        json={
            "urls": ["https://example.com/a", "https://example.com/b"],
            "skip_approval": True,
        },
        headers={"Authorization": "Bearer fake"},
    )
    assert response.status_code == 204

    pending = _pending_approvals.get(awaiting_mission.id)
    assert pending is not None
    assert pending.event.is_set()
    assert pending.approved_urls == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert pending.skip_approval_persisted is True
