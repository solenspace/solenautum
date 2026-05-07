from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import Enum as PyEnum, StrEnum
from typing import Any

from sqlalchemy import Column, Enum as SAEnum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlmodel import Field, SQLModel


def _enum_values(enum_cls: type[PyEnum]) -> Sequence[str]:
    """Render Postgres-side enum members from StrEnum *values*, not member
    names. Without this, SQLAlchemy emits uppercase names that mismatch
    `server_default` strings and Python-side `StrEnum` values.
    """
    return [e.value for e in enum_cls]


class MissionMode(StrEnum):
    URL = "url"
    DESCRIPTION = "description"


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Tier(StrEnum):
    HTTP = "http"
    STEALTH = "stealth"
    DYNAMIC = "dynamic"


class MissionPhase(StrEnum):
    """Description-mode workflow position. URL-mode missions move
    `null → scraping → done`; description-mode walks the full chain.
    Distinct from `Status` (lifecycle) which lives on the same row.
    """

    DISCOVERING = "discovering"
    AWAITING_APPROVAL = "awaiting_approval"
    SCRAPING = "scraping"
    DONE = "done"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True, max_length=64)  # Clerk user_id
    email: str = Field(max_length=320, index=True)
    created_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")},
    )


class Mission(SQLModel, table=True):
    __tablename__ = "missions"

    id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
    )
    user_id: str = Field(
        sa_column=Column(
            String(64),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    prompt: str = Field(max_length=2000)
    mode: MissionMode = Field(
        sa_column=Column(
            SAEnum(MissionMode, name="mission_mode", values_callable=_enum_values),
            nullable=False,
        ),
    )
    status: Status = Field(
        default=Status.PENDING,
        sa_column=Column(
            SAEnum(Status, name="mission_status", values_callable=_enum_values),
            nullable=False,
            server_default=Status.PENDING.value,
        ),
    )
    cost_cents: int = Field(default=0)
    robots_override: bool = Field(default=False)
    phase: MissionPhase | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(MissionPhase, name="mission_phase", values_callable=_enum_values),
            nullable=True,
        ),
    )
    skip_approval: bool = Field(
        default=False,
        sa_column_kwargs={"server_default": text("false"), "nullable": False},
    )
    discovered_urls: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    approved_urls: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    created_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")},
    )
    finished_at: datetime | None = None

    __table_args__ = (Index("ix_missions_user_id_status", "user_id", "status"),)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
    )
    mission_id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    url: str = Field(max_length=2048)
    tier_used: Tier = Field(
        sa_column=Column(
            SAEnum(Tier, name="task_tier", values_callable=_enum_values),
            nullable=False,
        ),
    )
    status: Status = Field(
        default=Status.PENDING,
        sa_column=Column(
            SAEnum(Status, name="task_status", values_callable=_enum_values),
            nullable=False,
            server_default=Status.PENDING.value,
        ),
    )
    latency_ms: int | None = None
    parsed_markdown: str | None = Field(default=None)
    snapshot_key: str | None = Field(default=None, max_length=512)
    snapshot_truncated: bool = Field(default=False)
    selector_cache_id: uuid.UUID | None = Field(default=None, foreign_key="saved_selectors.id")
    started_at: datetime | None = None
    finished_at: datetime | None = None


class SavedSelector(SQLModel, table=True):
    __tablename__ = "saved_selectors"

    id: uuid.UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
            nullable=False,
        ),
    )
    domain: str = Field(max_length=253, index=True)
    purpose: str = Field(max_length=64, index=True)
    payload: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    hit_count: int = Field(default=0)
    failure_count: int = Field(
        default=0,
        sa_column_kwargs={"server_default": text("0"), "nullable": False},
    )
    last_used_at: datetime = Field(
        sa_column_kwargs={"server_default": text("now()")},
    )

    __table_args__ = (
        Index(
            "ix_saved_selectors_domain_purpose",
            "domain",
            "purpose",
            unique=True,
        ),
    )
