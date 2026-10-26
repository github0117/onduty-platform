"""agent presence

Revision ID: f6c1d9b4a873
Revises: e5b9c3d1a762
Create Date: 2026-10-24 22:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f6c1d9b4a873"
down_revision: str | None = "e5b9c3d1a762"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_presence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_conversation_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_agent_presence_agent"),
    )
    op.create_index(
        "ix_agent_presence_last_seen",
        "agent_presence",
        ["last_seen_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_presence_last_seen", table_name="agent_presence")
    op.drop_table("agent_presence")
