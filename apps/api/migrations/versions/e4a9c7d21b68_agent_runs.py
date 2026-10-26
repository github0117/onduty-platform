"""agent runs

Revision ID: e4a9c7d21b68
Revises: d7f6e1a4c923
Create Date: 2026-10-23 15:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "e4a9c7d21b68"
down_revision: str | None = "d7f6e1a4c923"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("run_type", sa.String(length=32), nullable=False),
        sa.Column("workflow_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("correlation_id"),
    )
    op.create_index(
        "ix_agent_runs_employee_time",
        "agent_runs",
        ["employee_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status_time",
        "agent_runs",
        ["status", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_ticket_time",
        "agent_runs",
        ["ticket_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_unit_time",
        "agent_runs",
        ["business_unit_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_unit_time", table_name="agent_runs")
    op.drop_index("ix_agent_runs_ticket_time", table_name="agent_runs")
    op.drop_index("ix_agent_runs_status_time", table_name="agent_runs")
    op.drop_index("ix_agent_runs_employee_time", table_name="agent_runs")
    op.drop_table("agent_runs")
