"""agent scheduling

Revision ID: d7a4c2e9f531
Revises: c3e9b1d7a245
Create Date: 2026-11-11 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d7a4c2e9f531"
down_revision: str | None = "c3e9b1d7a245"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_scheduling_policies",
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("enforce_published_schedule", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("business_unit_id"),
    )
    op.create_table(
        "agent_shift_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("start_local", sa.Time(), nullable=False),
        sa.Column("end_local", sa.Time(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "name",
            name="uq_agent_shift_templates_unit_name",
        ),
    )
    op.create_index(
        "ix_agent_shift_templates_unit_status",
        "agent_shift_templates",
        ["business_unit_id", "status"],
        unique=False,
    )
    op.create_table(
        "agent_rosters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cloned_from_roster_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("published_by", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cloned_from_roster_id"],
            ["agent_rosters.id"],
            name="fk_agent_rosters_cloned_from",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_rosters_unit_week",
        "agent_rosters",
        ["business_unit_id", "week_start"],
        unique=False,
    )
    op.create_index(
        "uq_agent_rosters_unit_week_draft",
        "agent_rosters",
        ["business_unit_id", "week_start"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
        sqlite_where=sa.text("status = 'DRAFT'"),
    )
    op.create_index(
        "uq_agent_rosters_unit_week_published",
        "agent_rosters",
        ["business_unit_id", "week_start"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
        sqlite_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "agent_roster_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("roster_id", sa.Uuid(), nullable=False),
        sa.Column("shift_template_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("agent_display_name", sa.String(length=200), nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shift_name", sa.String(length=100), nullable=False),
        sa.Column("shift_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["roster_id"],
            ["agent_rosters.id"],
            name="fk_agent_roster_entries_roster",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shift_template_id"],
            ["agent_shift_templates.id"],
            name="fk_agent_roster_entries_shift",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "roster_id",
            "agent_id",
            "shift_date",
            name="uq_agent_roster_entries_agent_day",
        ),
    )
    op.create_index(
        "ix_agent_roster_entries_agent_window",
        "agent_roster_entries",
        ["agent_id", "start_at", "end_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_roster_entries_roster_window",
        "agent_roster_entries",
        ["roster_id", "start_at", "end_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_roster_entries_roster_window",
        table_name="agent_roster_entries",
    )
    op.drop_index(
        "ix_agent_roster_entries_agent_window",
        table_name="agent_roster_entries",
    )
    op.drop_table("agent_roster_entries")
    op.drop_index("uq_agent_rosters_unit_week_published", table_name="agent_rosters")
    op.drop_index("uq_agent_rosters_unit_week_draft", table_name="agent_rosters")
    op.drop_index("ix_agent_rosters_unit_week", table_name="agent_rosters")
    op.drop_table("agent_rosters")
    op.drop_index(
        "ix_agent_shift_templates_unit_status",
        table_name="agent_shift_templates",
    )
    op.drop_table("agent_shift_templates")
    op.drop_table("agent_scheduling_policies")
