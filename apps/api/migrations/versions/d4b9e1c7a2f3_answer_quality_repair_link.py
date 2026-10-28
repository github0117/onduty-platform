"""link answer quality evaluations to repair tasks

Revision ID: d4b9e1c7a2f3
Revises: c8f3a7d2b941
Create Date: 2026-10-28 14:00:00.000000

A failed spot check should end in one repair task, not in a dashboard number.
The link is nullable because most evaluations pass and older rows predate it;
deleting a repair task clears the link but keeps the verdict.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b9e1c7a2f3"
down_revision: str | None = "c8f3a7d2b941"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("answer_quality_evaluations") as batch:
        batch.add_column(sa.Column("repair_task_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_answer_quality_evaluations_repair_task",
            "knowledge_repair_tasks",
            ["repair_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_answer_quality_evaluations_repair_task_id",
            ["repair_task_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("answer_quality_evaluations") as batch:
        batch.drop_index("ix_answer_quality_evaluations_repair_task_id")
        batch.drop_constraint(
            "fk_answer_quality_evaluations_repair_task",
            type_="foreignkey",
        )
        batch.drop_column("repair_task_id")
