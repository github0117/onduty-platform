"""workforce supervisor tasks

Revision ID: f1a6d8c4b792
Revises: e4b8c2f7a951
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6d8c4b792"
down_revision: str | None = "e4b8c2f7a951"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workforce_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("supervisor_employee_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["supervisor_employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workforce_tasks_unit_status",
        "workforce_tasks",
        ["business_unit_id", "status", "created_at"],
    )
    op.create_table(
        "workforce_task_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("assigned_employee_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_employee_key", sa.String(length=100), nullable=False),
        sa.Column("route_decision_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assigned_employee_id"],
            ["digital_employees.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["workforce_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "sequence",
            name="uq_workforce_task_step_sequence",
        ),
    )
    op.create_index(
        "ix_workforce_task_steps_task_id",
        "workforce_task_steps",
        ["task_id"],
    )
    op.create_index(
        "ix_workforce_task_steps_employee_status",
        "workforce_task_steps",
        ["assigned_employee_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workforce_task_steps_employee_status",
        table_name="workforce_task_steps",
    )
    op.drop_index(
        "ix_workforce_task_steps_task_id",
        table_name="workforce_task_steps",
    )
    op.drop_table("workforce_task_steps")
    op.drop_index(
        "ix_workforce_tasks_unit_status",
        table_name="workforce_tasks",
    )
    op.drop_table("workforce_tasks")
