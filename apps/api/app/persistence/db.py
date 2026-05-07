from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.security import _current_user


@lru_cache(maxsize=1)
def _get_engine() -> AsyncEngine:
    """Lazily build the async engine. Fails fast if DATABASE_URL is unset."""
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not set; persistence-layer features are disabled.")
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        _get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )


def require_user_id() -> str:
    """Application-layer ownership check. Repository methods that read or
    write user-owned data call this to enforce ownership *before* the SQL
    runs; RLS is the defense-in-depth backstop. Raises if no user is bound.
    """
    user = _current_user.get()
    if user is None:
        raise RuntimeError(
            "Repository called outside an authenticated context. "
            "Bind _current_user before invoking mission/task methods."
        )
    return user.user_id


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    """Open a transaction with `SET LOCAL app.user_id` bound from the contextvar.

    The `SET LOCAL` only fires when a user is bound (i.e., on authenticated
    routes); the `users` table is intentionally written without binding because
    it has no RLS — it is identity, not user data.
    """
    user = _current_user.get()
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        if user is not None:
            # `SET LOCAL <name> = $1` is rejected by Postgres' parser
            # (asyncpg `prepare` raises `syntax error at or near "$1"`).
            # `set_config(name, value, is_local=true)` accepts a bound
            # parameter and is the canonical equivalent.
            await session.execute(
                text("SELECT set_config('app.user_id', :uid, true)").bindparams(uid=user.user_id),
            )
        yield session


@asynccontextmanager
async def system_transaction() -> AsyncIterator[AsyncSession]:
    """Open a transaction that bypasses RLS for cross-user system tasks
    (the orphan reaper). Issues `SET LOCAL row_security = off` so the
    UPDATE can scan every user's `missions` row.

    Connection-role requirement: the role must have either superuser or
    `BYPASSRLS`. Neon's `neondb_owner` satisfies this; local dev with the
    default Postgres superuser also satisfies it. If a deployment uses a
    role without bypass capability, the reaper will surface a permission
    error in logs on first sweep — escalate by granting `BYPASSRLS` on
    that role rather than weakening the application's RLS posture.

    Never use for user-initiated routes; those always go through
    `transaction()` so RLS is the backstop on a misrouted query.
    """
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL row_security = off"))
        yield session
