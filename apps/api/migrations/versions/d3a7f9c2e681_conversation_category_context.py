"""conversation category context

Revision ID: d3a7f9c2e681
Revises: c1a6e8d3f572
Create Date: 2026-10-25 00:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3a7f9c2e681"
down_revision: str | None = "c1a6e8d3f572"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer_conversations",
        sa.Column("category_name", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "customer_conversations",
        sa.Column("category_profile_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_conversations", "category_profile_id")
    op.drop_column("customer_conversations", "category_name")
