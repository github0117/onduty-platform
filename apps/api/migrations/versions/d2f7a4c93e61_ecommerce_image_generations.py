"""ecommerce image generations

Revision ID: d2f7a4c93e61
Revises: c9e4f2a7b631
Create Date: 2026-10-23 17:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d2f7a4c93e61"
down_revision: str | None = "c9e4f2a7b631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_image_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("prompt", sa.String(length=2000), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["ecommerce_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_image_generations_product_time",
        "ecommerce_image_generations",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ecommerce_image_generations_unit_time",
        "ecommerce_image_generations",
        ["business_unit_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_image_generations_unit_time",
        table_name="ecommerce_image_generations",
    )
    op.drop_index(
        "ix_ecommerce_image_generations_product_time",
        table_name="ecommerce_image_generations",
    )
    op.drop_table("ecommerce_image_generations")
