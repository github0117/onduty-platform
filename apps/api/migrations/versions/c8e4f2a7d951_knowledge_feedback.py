"""knowledge feedback

Revision ID: c8e4f2a7d951
Revises: b2e6f8a1c943
Create Date: 2026-10-24 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c8e4f2a7d951"
down_revision: str | None = "b2e6f8a1c943"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_space_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("repair_task_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_space_id"],
            ["knowledge_spaces.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["repair_task_id"],
            ["knowledge_repair_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_feedback_unit_rating",
        "knowledge_feedback",
        ["business_unit_id", "rating"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_feedback_created",
        "knowledge_feedback",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_feedback_created",
        table_name="knowledge_feedback",
    )
    op.drop_index(
        "ix_knowledge_feedback_unit_rating",
        table_name="knowledge_feedback",
    )
    op.drop_table("knowledge_feedback")
