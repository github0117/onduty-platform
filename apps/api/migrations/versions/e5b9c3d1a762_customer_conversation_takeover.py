"""customer conversation takeover lock

Revision ID: e5b9c3d1a762
Revises: d4f8a2c7e961
Create Date: 2026-10-24 22:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5b9c3d1a762"
down_revision: str | None = "d4f8a2c7e961"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "customer_conversations",
        sa.Column("assigned_agent_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "customer_conversations",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "customer_conversations",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("customer_conversations", "version")
    op.drop_column("customer_conversations", "assigned_at")
    op.drop_column("customer_conversations", "assigned_agent_id")
