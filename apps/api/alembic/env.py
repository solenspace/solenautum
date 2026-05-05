from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app.config import settings
from app.persistence import models  # noqa: F401  imported for SQLModel registration

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def _require_unpooled_url() -> str:
    if settings.database_url_unpooled is None:
        raise RuntimeError(
            "DATABASE_URL_UNPOOLED is required for alembic; Neon's transaction "
            "pooler rejects session-level features that alembic uses."
        )
    return settings.database_url_unpooled


def run_migrations_offline() -> None:
    context.configure(
        url=_require_unpooled_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_require_unpooled_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
