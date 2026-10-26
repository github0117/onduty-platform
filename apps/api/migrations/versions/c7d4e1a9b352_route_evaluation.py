"""route evaluation cases and runs

Revision ID: c7d4e1a9b352
Revises: b1f7a2c9e4d6
Create Date: 2026-10-27 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c7d4e1a9b352"
down_revision: str | None = "b1f7a2c9e4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_employee_route_evaluation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("service_entry_id", sa.Uuid(), nullable=False),
        sa.Column("expected_employee_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_entry_id"],
            ["business_service_entries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["expected_employee_id"],
            ["digital_employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "service_entry_id",
            "question",
            name="uq_route_evaluation_case_question",
        ),
    )
    op.create_index(
        "ix_route_evaluation_cases_entry_enabled",
        "digital_employee_route_evaluation_cases",
        ["service_entry_id", "enabled"],
        unique=False,
    )
    op.create_table(
        "digital_employee_route_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("service_entry_id", sa.Uuid(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["service_entry_id"],
            ["business_service_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_route_evaluation_runs_unit_time",
        "digital_employee_route_evaluation_runs",
        ["business_unit_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_route_evaluation_runs_unit_time",
        table_name="digital_employee_route_evaluation_runs",
    )
    op.drop_table("digital_employee_route_evaluation_runs")
    op.drop_index(
        "ix_route_evaluation_cases_entry_enabled",
        table_name="digital_employee_route_evaluation_cases",
    )
    op.drop_table("digital_employee_route_evaluation_cases")
