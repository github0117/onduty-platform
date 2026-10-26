"""ecommerce product listing

Revision ID: b7d3e8f14a52
Revises: e4a9c7d21b68
Create Date: 2026-10-23 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b7d3e8f14a52"
down_revision: str | None = "e4a9c7d21b68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "sku",
            name="uq_ecommerce_product_unit_sku",
        ),
    )
    op.create_index(
        "ix_ecommerce_products_unit_status",
        "ecommerce_products",
        ["business_unit_id", "status"],
        unique=False,
    )
    op.create_table(
        "ecommerce_listing_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("compliance_json", sa.JSON(), nullable=False),
        sa.Column("citations_json", sa.JSON(), nullable=False),
        sa.Column("generator_provider", sa.String(length=64), nullable=False),
        sa.Column("generator_model", sa.String(length=160), nullable=False),
        sa.Column("human_reason", sa.String(length=64), nullable=True),
        sa.Column("external_listing_id", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["ecommerce_products.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_listing_product_time",
        "ecommerce_listing_tasks",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ecommerce_listing_unit_status",
        "ecommerce_listing_tasks",
        ["business_unit_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_listing_unit_status",
        table_name="ecommerce_listing_tasks",
    )
    op.drop_index(
        "ix_ecommerce_listing_product_time",
        table_name="ecommerce_listing_tasks",
    )
    op.drop_table("ecommerce_listing_tasks")
    op.drop_index(
        "ix_ecommerce_products_unit_status",
        table_name="ecommerce_products",
    )
    op.drop_table("ecommerce_products")
