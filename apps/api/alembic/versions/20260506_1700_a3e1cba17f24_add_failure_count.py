"""add_failure_count

Revision ID: a3e1cba17f24
Revises: f1ee8b2b94b2
Create Date: 2026-05-06 17:00:00.000000

Adds the `failure_count` column to `saved_selectors` (Spec 13). The column
backs the three-strikes eviction policy: every adaptive selector lookup
that produces zero hits bumps the count, and the row is deleted once it
crosses three. NOT NULL with a `0` server default so existing rows
backfill cleanly without an explicit UPDATE.

`saved_selectors` has no RLS (deployment-scoped per architecture
decision), so no policy changes are needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3e1cba17f24"
down_revision: str | Sequence[str] | None = "f1ee8b2b94b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "saved_selectors",
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("saved_selectors", "failure_count")
