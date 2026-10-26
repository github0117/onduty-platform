"""supervisor notifications

Revision ID: a9e7c2f5b134
Revises: f6c1d9b4a873
Create Date: 2026-10-24 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a9e7c2f5b134"
down_revision: str | None = "f6c1d9b4a873"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_service_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_service_notifications_status",
        "customer_service_notifications",
        ["business_unit_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_customer_service_notifications_conversation",
        "customer_service_notifications",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_service_notifications_conversation",
        table_name="customer_service_notifications",
    )
    op.drop_index(
        "ix_customer_service_notifications_status",
        table_name="customer_service_notifications",
    )
    op.drop_table("customer_service_notifications")
