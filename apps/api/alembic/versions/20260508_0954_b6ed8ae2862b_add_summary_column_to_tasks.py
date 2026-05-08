"""add summary column to tasks

Revision ID: b6ed8ae2862b
Revises: a3e1cba17f24
Create Date: 2026-05-08 09:54:13.669261

The agent already produces a per-task `summary` (one-paragraph
description of what was scraped) inside `MissionResult.summary`, but
the runner never persisted it. Without a column to land it in, the
mission detail UI had nothing to anchor a "what did this scrape
actually find" card.

Add a nullable `summary` text column so the runner can write it on
task termination and `GET /missions/{id}` can return it. Nullable so
existing rows do not break the migration; the runner leaves it null
when the agent failed before producing a summary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6ed8ae2862b"
down_revision: str | Sequence[str] | None = "a3e1cba17f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "summary")
