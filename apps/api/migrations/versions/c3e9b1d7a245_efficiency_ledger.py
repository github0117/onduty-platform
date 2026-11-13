"""efficiency ledger

Revision ID: c3e9b1d7a245
Revises: b5e2a8d9c641
Create Date: 2026-11-11 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3e9b1d7a245"
down_revision: str | None = "b5e2a8d9c641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "efficiency_assumptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("hourly_labor_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("minutes_per_ticket", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "minutes_per_conversation",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column("minutes_per_listing", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            name="uq_efficiency_assumptions_unit",
        ),
    )

    op.create_table(
        "efficiency_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "human_minutes_saved",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "labor_cost_saved",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("assumption_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            name="fk_efficiency_ledger_employee",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "source_type",
            "source_id",
            name="uq_efficiency_ledger_source",
        ),
    )
    op.create_index(
        "ix_efficiency_ledger_unit_occurred",
        "efficiency_ledger_entries",
        ["business_unit_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_efficiency_ledger_unit_employee",
        "efficiency_ledger_entries",
        ["business_unit_id", "employee_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_efficiency_ledger_unit_employee",
        table_name="efficiency_ledger_entries",
    )
    op.drop_index(
        "ix_efficiency_ledger_unit_occurred",
        table_name="efficiency_ledger_entries",
    )
    op.drop_table("efficiency_ledger_entries")
    op.drop_table("efficiency_assumptions")
