from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlmodel import select
from sqlmodel.sql.expression import SelectOfScalar

from app.persistence.db import require_user_id, transaction
from app.persistence.models import (
    Mission,
    MissionMode,
    SavedSelector,
    Status,
    Task,
    Tier,
    User,
)


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
    ) -> Mission:
        user_id = require_user_id()
        async with transaction() as session:
            mission = Mission(
                user_id=user_id,
                prompt=prompt,
                mode=mode,
                robots_override=robots_override,
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

    async def update_status(self, mission_id: uuid.UUID, status: Status) -> None:
        user_id = require_user_id()
        async with transaction() as session:
            mission = (await session.exec(_owned_mission_stmt(mission_id, user_id))).first()
            if mission is None:
                return
            mission.status = status
            if status in {Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}:
                mission.finished_at = datetime.now(UTC)


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


class SelectorRepository:
    """Selector cache is deployment-scoped (architecture decision). No
    `_current_user` filter; saved_selectors has no RLS policy.
    """

    async def get(self, domain: str, purpose: str) -> SavedSelector | None:
        async with transaction() as session:
            stmt = select(SavedSelector).where(
                SavedSelector.domain == domain,
                SavedSelector.purpose == purpose,
            )
            return (await session.exec(stmt)).first()

    async def upsert(self, *, domain: str, purpose: str, payload: dict[str, Any]) -> SavedSelector:
        # Spec 13 replaces this SELECT-then-INSERT with `INSERT ... ON CONFLICT
        # DO UPDATE` to close the race window. Until then, concurrent upserts
        # on the same (domain, purpose) can collide on the unique index.
        async with transaction() as session:
            stmt = select(SavedSelector).where(
                SavedSelector.domain == domain,
                SavedSelector.purpose == purpose,
            )
            existing = (await session.exec(stmt)).first()
            if existing is None:
                selector = SavedSelector(domain=domain, purpose=purpose, payload=payload)
                session.add(selector)
                await session.flush()
                await session.refresh(selector)
                return selector
            existing.payload = payload
            existing.hit_count += 1
            existing.last_used_at = datetime.now(UTC)
            await session.flush()
            await session.refresh(existing)
            return existing


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
