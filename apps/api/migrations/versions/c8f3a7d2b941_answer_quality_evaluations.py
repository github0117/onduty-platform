"""answer quality evaluations

Revision ID: c8f3a7d2b941
Revises: b7e2c4a9f105
Create Date: 2026-10-28 13:30:00.000000

Human spot checks of adopted answer drafts. One row per draft so a re-check
updates the verdict instead of duplicating it, and the sampling queue can
exclude already reviewed answers with a simple anti-join.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f3a7d2b941"
down_revision: str | None = "b7e2c4a9f105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_quality_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column(
            "hallucinated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evaluator_ref", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["answer_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "draft_id",
            name="uq_answer_quality_evaluations_draft",
        ),
    )
    op.create_index(
        "ix_answer_quality_evaluations_business_unit_id",
        "answer_quality_evaluations",
        ["business_unit_id"],
        unique=False,
    )
    op.create_index(
        "ix_answer_quality_evaluations_unit_created",
        "answer_quality_evaluations",
        ["business_unit_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_answer_quality_evaluations_unit_created",
        table_name="answer_quality_evaluations",
    )
    op.drop_index(
        "ix_answer_quality_evaluations_business_unit_id",
        table_name="answer_quality_evaluations",
    )
    op.drop_table("answer_quality_evaluations")
