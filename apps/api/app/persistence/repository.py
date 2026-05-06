from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete as sa_delete, func, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from app.persistence.db import require_user_id, transaction
from app.persistence.models import (
    Mission,
    MissionMode,
    MissionPhase,
    SavedSelector,
    Status,
    Task,
    Tier,
    User,
)
from app.persistence.selector_cache import cache_evict, cache_get, cache_put


def _owned_mission_stmt(mission_id: uuid.UUID, user_id: str) -> SelectOfScalar[Mission]:
    return select(Mission).where(Mission.id == mission_id, Mission.user_id == user_id)


def _owned_task_stmt(task_id: uuid.UUID, user_id: str) -> SelectOfScalar[Task]:
    # Implicit join via the Task→Mission FK; SQLAlchemy infers the on-clause.
    return select(Task).join(Mission).where(Task.id == task_id, Mission.user_id == user_id)


class MissionRepository:
    async def create(
        self,
        *,
        prompt: str,
        mode: MissionMode,
        robots_override: bool = False,
        skip_approval: bool = False,
    ) -> Mission:
        user_id = require_user_id()
        async with transaction() as session:
            mission = Mission(
                user_id=user_id,
                prompt=prompt,
                mode=mode,
                robots_override=robots_override,
                skip_approval=skip_approval,
            )
            session.add(mission)
            await session.flush()
            await session.refresh(mission)
            return mission

    async def get(self, mission_id: uuid.UUID) -> Mission | None:
        user_id = require_user_id()
        async with transaction() as session:
            return (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()

    async def list_by_status(self, status: Status) -> list[Mission]:
        user_id = require_user_id()
        async with transaction() as session:
            stmt = select(Mission).where(
                Mission.status == status,
                Mission.user_id == user_id,
            )
            return list((await session.exec(stmt)).all())

    async def list_all(self) -> list[Mission]:
        """Every mission owned by the current user, newest first.

        RLS would back-stop a missing `user_id` filter, but the application
        layer always filters explicitly per `code-standards.md` so a logic bug
        is a 0-row result, not a cross-tenant leak.
        """
        user_id = require_user_id()
        async with transaction() as session:
            stmt = (
                select(Mission)
                .where(Mission.user_id == user_id)
                .order_by(Mission.created_at.desc())  # type: ignore[attr-defined]
            )
            return list((await session.exec(stmt)).all())

    async def update_status(self, mission_id: uuid.UUID, status: Status) -> None:
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.status = status
            if status in {Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}:
                mission.finished_at = datetime.now(UTC)

    async def set_phase(self, mission_id: uuid.UUID, phase: MissionPhase) -> None:
        """Workflow position update — orthogonal to `status`. Description-mode
        missions walk all four phases; URL-mode jumps `null → scraping → done`."""
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.phase = phase

    async def set_discovered_urls(self, mission_id: uuid.UUID, urls: list[dict[str, Any]]) -> None:
        """Persist Tavily's result list verbatim. Immutable once written —
        re-discovery would create a new mission row."""
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.discovered_urls = urls

    async def set_approved_urls(self, mission_id: uuid.UUID, urls: list[str]) -> None:
        """User-approved subset of `discovered_urls`. Set once at approval-gate
        submit; the runner reads this value to construct task rows."""
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.approved_urls = urls

    async def set_skip_approval(self, mission_id: uuid.UUID, value: bool) -> None:
        """Per-mission flag honored by future re-search calls in the same
        mission. No cross-mission persistence (Spec 12 scope)."""
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.skip_approval = value


class TaskRepository:
    async def create(
        self,
        *,
        mission_id: uuid.UUID,
        url: str,
        tier_used: Tier,
    ) -> Task:
        user_id = require_user_id()
        async with transaction() as session:
            # Validate ownership before INSERT so cross-tenant attempts raise
            # loudly instead of being silently rejected by RLS WITH CHECK.
            owned = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if owned is None:
                raise PermissionError(f"mission {mission_id} not found for user {user_id}")
            task = Task(mission_id=mission_id, url=url, tier_used=tier_used)
            session.add(task)
            await session.flush()
            await session.refresh(task)
            return task

    async def get(self, task_id: uuid.UUID) -> Task | None:
        user_id = require_user_id()
        async with transaction() as session:
            return (await session.exec(_owned_task_stmt(task_id, user_id))).first()

    async def list_by_mission(self, mission_id: uuid.UUID) -> list[Task]:
        """All tasks belonging to one mission, ownership-scoped via the
        Task→Mission join. Used by the runner to compute the rolled-up
        mission status after the TaskGroup exits.
        """
        user_id = require_user_id()
        async with transaction() as session:
            stmt = (
                select(Task)
                .join(Mission)
                .where(Task.mission_id == mission_id, Mission.user_id == user_id)
            )
            return list((await session.exec(stmt)).all())

    async def update(
        self,
        task_id: uuid.UUID,
        *,
        status: Status | None = None,
        latency_ms: int | None = None,
        parsed_markdown: str | None = None,
        snapshot_key: str | None = None,
        snapshot_truncated: bool | None = None,
        selector_cache_id: uuid.UUID | None = None,
    ) -> None:
        user_id = require_user_id()
        async with transaction() as session:
            task = (await session.exec(_owned_task_stmt(task_id, user_id))).first()
            if task is None:
                return
            if status is not None:
                task.status = status
                if status == Status.RUNNING and task.started_at is None:
                    task.started_at = datetime.now(UTC)
                if status in {Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}:
                    task.finished_at = datetime.now(UTC)
            if latency_ms is not None:
                task.latency_ms = latency_ms
            if parsed_markdown is not None:
                task.parsed_markdown = parsed_markdown
            if snapshot_key is not None:
                task.snapshot_key = snapshot_key
            if snapshot_truncated is not None:
                task.snapshot_truncated = snapshot_truncated
            if selector_cache_id is not None:
                task.selector_cache_id = selector_cache_id


_FAILURE_THRESHOLD = 3


def _to_cache_dict(row: SavedSelector) -> dict[str, Any]:
    """Cache shape — chosen so callers of `find()` can reconstruct a
    transient `SavedSelector` and `ProcessLruStorage.retrieve` can pluck
    the `payload` directly. Keeping `id` and `last_used_at` lets future
    observability surfaces correlate cache hits with DB rows.
    """
    return {
        "id": str(row.id),
        "payload": row.payload,
        "hit_count": row.hit_count,
        "failure_count": row.failure_count,
        "last_used_at": row.last_used_at.isoformat(),
    }


def _from_cache_dict(domain: str, purpose: str, cached: dict[str, Any]) -> SavedSelector:
    return SavedSelector(
        id=uuid.UUID(cached["id"]),
        domain=domain,
        purpose=purpose,
        payload=cached["payload"],
        hit_count=cached["hit_count"],
        failure_count=cached["failure_count"],
        last_used_at=datetime.fromisoformat(cached["last_used_at"]),
    )


class SelectorRepository:
    """Selector cache is deployment-scoped (architecture decision). No
    `_current_user` filter; `saved_selectors` has no RLS policy. The
    `transaction()` context still binds `app.user_id` when one is set —
    harmless for this table because its policies don't reference it.

    Read-through / write-through to the in-process LRU at
    `app/persistence/selector_cache.py`. Eviction layers, in order of
    precedence: LRU bound (silent), TTL sweep (Spec 13's
    `selector_sweep_loop`), and consecutive-failure threshold.
    """

    async def find(self, domain: str, purpose: str) -> SavedSelector | None:
        cached = cache_get(domain, purpose)
        if cached is not None:
            return _from_cache_dict(domain, purpose, cached)

        async with transaction() as session:
            stmt = select(SavedSelector).where(
                SavedSelector.domain == domain,
                SavedSelector.purpose == purpose,
            )
            row = (await session.exec(stmt)).first()
            if row is None:
                return None
            cache_put(domain, purpose, _to_cache_dict(row))
            return row

    async def upsert(self, *, domain: str, purpose: str, payload: dict[str, Any]) -> SavedSelector:
        """Atomic upsert via Postgres `INSERT ... ON CONFLICT DO UPDATE`.

        Closes Open Question 6 (the SELECT-then-INSERT race window in the
        previous implementation). On conflict we overwrite `payload`,
        reset `failure_count` to 0 (a fresh save invalidates the
        three-strikes counter), and bump `last_used_at`. We deliberately
        do *not* touch `hit_count` here — that's `bump_hit_count`'s job.
        """
        now = datetime.now(UTC)
        stmt = (
            pg_insert(SavedSelector)
            .values(
                domain=domain,
                purpose=purpose,
                payload=payload,
                hit_count=0,
                failure_count=0,
                last_used_at=now,
            )
            .on_conflict_do_update(
                index_elements=["domain", "purpose"],
                set_={
                    "payload": payload,
                    "failure_count": 0,
                    "last_used_at": now,
                },
            )
            .returning(SavedSelector)
        )
        async with transaction() as session:
            result = await session.execute(stmt)
            row: SavedSelector = result.scalar_one()
            cache_put(domain, purpose, _to_cache_dict(row))
            return row

    async def bump_hit_count(self, domain: str, purpose: str) -> int:
        """Atomic `UPDATE ... SET hit_count = hit_count + 1` + cache refresh.

        Caller must hold the invariant that the row exists (the recovery
        path always finds an existing selector before bumping). If the
        row was concurrently evicted, returns 0 — the next adaptive miss
        will recreate it via `upsert`.
        """
        stmt = (
            update(SavedSelector)
            .where(
                col(SavedSelector.domain) == domain,
                col(SavedSelector.purpose) == purpose,
            )
            .values(
                hit_count=SavedSelector.hit_count + 1,
                last_used_at=datetime.now(UTC),
            )
            .returning(SavedSelector)
        )
        async with transaction() as session:
            result = await session.execute(stmt)
            row: SavedSelector | None = result.scalar_one_or_none()
            if row is None:
                cache_evict(domain, purpose)
                return 0
            cache_put(domain, purpose, _to_cache_dict(row))
            return int(row.hit_count)

    async def bump_failure_count(self, domain: str, purpose: str) -> int:
        """Increment failure_count; auto-delete the row when it crosses the
        three-strikes threshold. Returns the new failure_count (post-bump).
        """
        async with transaction() as session:
            stmt = (
                update(SavedSelector)
                .where(
                    col(SavedSelector.domain) == domain,
                    col(SavedSelector.purpose) == purpose,
                )
                .values(failure_count=SavedSelector.failure_count + 1)
                .returning(SavedSelector)
            )
            result = await session.execute(stmt)
            row: SavedSelector | None = result.scalar_one_or_none()
            if row is None:
                cache_evict(domain, purpose)
                return 0
            new_count = int(row.failure_count)
            if new_count >= _FAILURE_THRESHOLD:
                await session.delete(row)
                cache_evict(domain, purpose)
            else:
                cache_put(domain, purpose, _to_cache_dict(row))
            return new_count

    async def delete(self, domain: str, purpose: str) -> None:
        async with transaction() as session:
            await session.execute(
                sa_delete(SavedSelector).where(
                    col(SavedSelector.domain) == domain,
                    col(SavedSelector.purpose) == purpose,
                )
            )
        cache_evict(domain, purpose)

    async def evict_older_than(self, *, days: int) -> int:
        """Delete rows where `last_used_at` is older than `days`. Returns
        the eviction count and clears matching cache entries.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with transaction() as session:
            stmt = (
                sa_delete(SavedSelector)
                .where(col(SavedSelector.last_used_at) < cutoff)
                .returning(col(SavedSelector.domain), col(SavedSelector.purpose))
            )
            evicted = list((await session.execute(stmt)).all())
        for evicted_domain, evicted_purpose in evicted:
            cache_evict(evicted_domain, evicted_purpose)
        return len(evicted)

    async def count_all(self) -> int:
        """Test-only helper for `evict_older_than` round-trip assertions."""
        async with transaction() as session:
            result = await session.execute(select(func.count()).select_from(SavedSelector))
            return int(result.scalar_one())


class UserRepository:
    """Webhook-only writer. The `users` table has no RLS — it is identity, not
    user data — and `transaction()` skips `SET LOCAL` when no user is bound,
    which is exactly the case for webhook traffic.
    """

    async def upsert(self, *, user_id: str, email: str) -> User:
        async with transaction() as session:
            user = await session.get(User, user_id)
            if user is None:
                user = User(id=user_id, email=email)
                session.add(user)
            else:
                user.email = email
            await session.flush()
            await session.refresh(user)
            return user

    async def delete(self, user_id: str) -> None:
        async with transaction() as session:
            user = await session.get(User, user_id)
            if user is not None:
                await session.delete(user)
