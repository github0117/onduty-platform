"""ecommerce product assets

Revision ID: c9e4f2a7b631
Revises: b7d3e8f14a52
Create Date: 2026-10-23 16:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c9e4f2a7b631"
down_revision: str | None = "b7d3e8f14a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_product_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["ecommerce_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_assets_product_time",
        "ecommerce_product_assets",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ecommerce_assets_unit_type",
        "ecommerce_product_assets",
        ["business_unit_id", "asset_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_assets_unit_type",
        table_name="ecommerce_product_assets",
    )
    op.drop_index(
        "ix_ecommerce_assets_product_time",
        table_name="ecommerce_product_assets",
    )
    op.drop_table("ecommerce_product_assets")
