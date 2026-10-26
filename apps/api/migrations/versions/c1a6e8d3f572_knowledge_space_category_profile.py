"""knowledge space category profile

Revision ID: c1a6e8d3f572
Revises: b8f3d1c6e274
Create Date: 2026-10-25 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1a6e8d3f572"
down_revision: str | None = "b8f3d1c6e274"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_spaces",
        sa.Column("category_profile_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_knowledge_spaces_category_profile_id",
        "knowledge_spaces",
        ["category_profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_spaces_category_profile_id",
        table_name="knowledge_spaces",
    )
    op.drop_column("knowledge_spaces", "category_profile_id")
