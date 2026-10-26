"""knowledge repair tasks

Revision ID: a7d1c4e9f632
Revises: f4c2d8e9a731
Create Date: 2026-10-24 20:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a7d1c4e9f632"
down_revision: str | None = "f4c2d8e9a731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_repair_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_space_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_case_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_titles_json", sa.JSON(), nullable=False),
        sa.Column("returned_titles_json", sa.JSON(), nullable=False),
        sa.Column("assignee_id", sa.String(length=128), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["evaluation_case_id"],
            ["knowledge_evaluation_cases.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"],
            ["knowledge_evaluation_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_space_id"],
            ["knowledge_spaces.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_repair_tasks_unit_status",
        "knowledge_repair_tasks",
        ["business_unit_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_repair_tasks_run",
        "knowledge_repair_tasks",
        ["evaluation_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_repair_tasks_run",
        table_name="knowledge_repair_tasks",
    )
    op.drop_index(
        "ix_knowledge_repair_tasks_unit_status",
        table_name="knowledge_repair_tasks",
    )
    op.drop_table("knowledge_repair_tasks")
