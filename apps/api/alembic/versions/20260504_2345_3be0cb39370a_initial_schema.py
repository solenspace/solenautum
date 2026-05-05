"""initial schema

Revision ID: 3be0cb39370a
Revises:
Create Date: 2026-05-04 23:45:01.905105

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3be0cb39370a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "saved_selectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column(
            "last_used_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_saved_selectors_domain_purpose",
        "saved_selectors",
        ["domain", "purpose"],
        unique=True,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.String(length=2000), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("url", "description", name="mission_mode"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="mission_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("robots_override", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Composite index covers WHERE user_id = ? via left-prefix scans;
    # a separate single-column ix_missions_user_id would be redundant.
    op.create_index(
        "ix_missions_user_id_status",
        "missions",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column(
            "tier_used",
            sa.Enum("http", "stealth", "dynamic", name="task_tier"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="task_status",
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("parsed_markdown", sa.Text(), nullable=True),
        sa.Column("snapshot_key", sa.String(length=512), nullable=True),
        sa.Column("snapshot_truncated", sa.Boolean(), nullable=False),
        sa.Column("selector_cache_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selector_cache_id"], ["saved_selectors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_mission_id"), "tasks", ["mission_id"], unique=False)

    # --- RLS on user-owned tables ----------------------------------------
    # `FORCE` ensures policies apply even to table owners — Neon's connection
    # user often is the table owner.
    op.execute("ALTER TABLE missions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE missions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY missions_owner ON missions "
        "USING (user_id = current_setting('app.user_id', true)) "
        "WITH CHECK (user_id = current_setting('app.user_id', true))"
    )

    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tasks_owner ON tasks "
        "USING (EXISTS ("
        "  SELECT 1 FROM missions m "
        "  WHERE m.id = tasks.mission_id "
        "    AND m.user_id = current_setting('app.user_id', true)"
        ")) "
        "WITH CHECK (EXISTS ("
        "  SELECT 1 FROM missions m "
        "  WHERE m.id = tasks.mission_id "
        "    AND m.user_id = current_setting('app.user_id', true)"
        "))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop policies before tables (PG would otherwise refuse the table drop
    # while the policy holds a reference). Drop tasks before missions because
    # the tasks policy joins to missions.
    op.execute("DROP POLICY IF EXISTS tasks_owner ON tasks")
    op.execute("ALTER TABLE tasks DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS missions_owner ON missions")
    op.execute("ALTER TABLE missions DISABLE ROW LEVEL SECURITY")

    op.drop_index(op.f("ix_tasks_mission_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_missions_user_id_status", table_name="missions")
    op.drop_table("missions")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index("ix_saved_selectors_domain_purpose", table_name="saved_selectors")
    op.drop_table("saved_selectors")

    # Drop enum types last; CREATE TABLE auto-creates them, DROP TABLE does
    # not auto-drop them (sqlalchemy's `Enum(..., name=...)` is reusable).
    sa.Enum(name="task_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="task_tier").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="mission_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="mission_mode").drop(op.get_bind(), checkfirst=True)
