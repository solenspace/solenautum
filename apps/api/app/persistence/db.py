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
            await session.execute(text("SET LOCAL app.user_id = :uid").bindparams(uid=user.user_id))
        yield session
