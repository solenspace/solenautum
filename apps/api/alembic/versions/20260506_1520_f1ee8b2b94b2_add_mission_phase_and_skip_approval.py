"""add_mission_phase_and_skip_approval

Revision ID: f1ee8b2b94b2
Revises: 3be0cb39370a
Create Date: 2026-05-06 15:20:35.867090

Adds the four columns needed for description-mode missions (Spec 12):
  * `phase` — workflow position (discovering / awaiting_approval /
    scraping / done). Nullable for backfill safety; new code writes
    `scraping` for URL-mode missions and walks the full state machine
    for description-mode.
  * `skip_approval` — per-mission flag persisted across discovery
    re-prompts. NOT NULL with `false` server default so existing rows
    backfill cleanly.
  * `discovered_urls` — JSONB list of `DiscoveredUrl`-shaped objects
    (immutable once written) used by the slide-over to re-render the
    approval gate after a refresh.
  * `approved_urls` — JSONB list of strings; subset of
    `discovered_urls.url` chosen by the user.

RLS on `missions` is row-scoped (`user_id = current_setting(...)`); new
columns inherit the existing policy automatically. No policy update
needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1ee8b2b94b2"
down_revision: str | Sequence[str] | None = "3be0cb39370a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_MISSION_PHASE_VALUES = ("discovering", "awaiting_approval", "scraping", "done")


def upgrade() -> None:
    """Upgrade schema."""
    # Create the enum type up-front so `op.add_column` can reference it
    # without alembic auto-creating it inline.
    mission_phase = postgresql.ENUM(
        *_MISSION_PHASE_VALUES,
        name="mission_phase",
    )
    mission_phase.create(op.get_bind(), checkfirst=False)

    op.add_column(
        "missions",
        sa.Column(
            "phase",
            postgresql.ENUM(*_MISSION_PHASE_VALUES, name="mission_phase", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "missions",
        sa.Column(
            "skip_approval",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "missions",
        sa.Column(
            "discovered_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "missions",
        sa.Column(
            "approved_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("missions", "approved_urls")
    op.drop_column("missions", "discovered_urls")
    op.drop_column("missions", "skip_approval")
    op.drop_column("missions", "phase")
    sa.Enum(*_MISSION_PHASE_VALUES, name="mission_phase").drop(op.get_bind(), checkfirst=True)
