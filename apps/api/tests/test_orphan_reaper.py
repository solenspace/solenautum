"""Spec 14 — `MissionRepository.reap_orphans` correctness.

Three concerns, one per test:
- A `pending` mission older than the cutoff is reaped to `cancelled`.
- A `running` mission with `phase=awaiting_approval` older than the
  cutoff is reaped (description-mode parked-on-approval-gate case).
- A mission younger than the cutoff is left alone.

Plus one integration test that the lifespan loop reaps once and logs.

The reaper uses `system_transaction()` which bypasses RLS so it can
scan all users' rows; the connection role on the test database must
have `BYPASSRLS` (Neon's `neondb_owner` and the local Postgres
superuser both satisfy this). If a deployment role lacks the attribute
the helper surfaces a permission error in logs on the first sweep.

DB-dependent; skips when `DATABASE_URL` is unset.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.config import settings
from app.jobs.orphan_reaper import orphan_reaper_loop
from app.persistence.db import system_transaction, transaction
from app.persistence.models import MissionMode, MissionPhase, Status
from app.persistence.repository import MissionRepository, UserRepository
from app.security import CurrentUser, _current_user

pytestmark = pytest.mark.skipif(
    settings.database_url is None,
    reason="DATABASE_URL is not set; reaper tests need Postgres",
)


_FIXTURE_USER_ID = "user_test_reaper"


@pytest.fixture
def fake_user() -> CurrentUser:
    return CurrentUser(user_id=_FIXTURE_USER_ID, session_id="sess_reaper")


@pytest_asyncio.fixture(autouse=True)
async def seed_user(fake_user: CurrentUser) -> None:
    _current_user.set(None)
    await UserRepository().upsert(user_id=fake_user.user_id, email="reaper@example.com")


async def _backdate_created_at(mission_id: UUID, *, age: timedelta) -> None:
    """Push a freshly-created mission's `created_at` back so the cutoff
    can fire without sleeping."""
    backdate = datetime.now(UTC) - age
    async with system_transaction() as session:
        await session.execute(
            text("UPDATE missions SET created_at = :ts WHERE id = :mid").bindparams(
                ts=backdate, mid=str(mission_id)
            )
        )


@pytest.mark.asyncio
async def test_reaper_marks_pending_older_than_cutoff(fake_user: CurrentUser) -> None:
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="stale", mode=MissionMode.URL)
    # Status defaults to PENDING — never flipped to RUNNING.
    await _backdate_created_at(mission.id, age=timedelta(hours=2))

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    count = await repo.reap_orphans(cutoff=cutoff)
    assert count >= 1

    fresh = await repo.get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED
    assert fresh.finished_at is not None


@pytest.mark.asyncio
async def test_reaper_marks_awaiting_approval_older_than_cutoff(
    fake_user: CurrentUser,
) -> None:
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="parked", mode=MissionMode.DESCRIPTION)
    await repo.update_status(mission.id, Status.RUNNING)
    await repo.set_phase(mission.id, MissionPhase.AWAITING_APPROVAL)
    await _backdate_created_at(mission.id, age=timedelta(hours=2))

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    count = await repo.reap_orphans(cutoff=cutoff)
    assert count >= 1

    fresh = await repo.get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED


@pytest.mark.asyncio
async def test_reaper_skips_recent_pending(fake_user: CurrentUser) -> None:
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="fresh", mode=MissionMode.URL)
    # No backdate — created_at is now.

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    await repo.reap_orphans(cutoff=cutoff)

    fresh = await repo.get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.PENDING


@pytest.mark.asyncio
async def test_reaper_skips_running_without_awaiting_approval(
    fake_user: CurrentUser,
) -> None:
    """A plain `running` mission (no `awaiting_approval`) is NOT reaped —
    detecting "stuck running" requires per-task heartbeats and is out of
    scope for Spec 14.
    """
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="active", mode=MissionMode.URL)
    await repo.update_status(mission.id, Status.RUNNING)
    await repo.set_phase(mission.id, MissionPhase.SCRAPING)
    await _backdate_created_at(mission.id, age=timedelta(hours=2))

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    await repo.reap_orphans(cutoff=cutoff)

    fresh = await repo.get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.RUNNING


@pytest.mark.asyncio
async def test_reaper_loop_runs_once_and_returns_on_cancel(
    fake_user: CurrentUser,
) -> None:
    """Drive the loop with a tiny interval and a tight timeout so the
    sweep runs once. Then cancel the task — the loop must exit cleanly.
    """
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="loop", mode=MissionMode.URL)
    await _backdate_created_at(mission.id, age=timedelta(seconds=10))

    task = asyncio.create_task(orphan_reaper_loop(interval_s=0.05, orphan_age=timedelta(seconds=1)))
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Mission should be reaped after the first sweep.
    _current_user.set(fake_user)
    fresh = await repo.get(mission.id)
    assert fresh is not None
    assert fresh.status == Status.CANCELLED


@pytest.mark.asyncio
async def test_reaper_is_idempotent(fake_user: CurrentUser) -> None:
    """Two sweeps in a row over the same data: the second returns 0
    because the first moved the rows out of the targeted statuses.
    """
    _current_user.set(fake_user)
    repo = MissionRepository()
    mission = await repo.create(prompt="dbl", mode=MissionMode.URL)
    await _backdate_created_at(mission.id, age=timedelta(hours=2))

    cutoff = datetime.now(UTC) - timedelta(hours=1)
    first = await repo.reap_orphans(cutoff=cutoff)
    second = await repo.reap_orphans(cutoff=cutoff)
    assert first >= 1
    assert second == 0
    _ = transaction  # keep import used for linters
