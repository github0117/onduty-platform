"""ecommerce category profiles

Revision ID: b8f3d1c6e274
Revises: a9e7c2f5b134
Create Date: 2026-10-24 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b8f3d1c6e274"
down_revision: str | None = "a9e7c2f5b134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_category_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("platform_category_id", sa.String(length=100), nullable=True),
        sa.Column("required_attributes_json", sa.JSON(), nullable=False),
        sa.Column("presales_keywords_json", sa.JSON(), nullable=False),
        sa.Column("aftersales_keywords_json", sa.JSON(), nullable=False),
        sa.Column("restricted_claims_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "channel",
            "code",
            name="uq_ecommerce_category_business_code",
        ),
    )
    op.create_index(
        "ix_ecommerce_categories_unit_status",
        "ecommerce_category_profiles",
        ["business_unit_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_categories_unit_status",
        table_name="ecommerce_category_profiles",
    )
    op.drop_table("ecommerce_category_profiles")
