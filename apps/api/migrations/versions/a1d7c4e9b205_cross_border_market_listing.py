"""cross border market listing

Revision ID: a1d7c4e9b205
Revises: f3c8a1d6b942
Create Date: 2026-10-24 10:30:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import context, op

revision: str = "a1d7c4e9b205"
down_revision: str | None = "f3c8a1d6b942"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    column_specs: dict[str, sa.Column[Any]] = {
        "market_code": sa.Column(
            "market_code",
            sa.String(length=16),
            server_default="CN",
            nullable=False,
        ),
        "locale": sa.Column(
            "locale",
            sa.String(length=20),
            server_default="zh-CN",
            nullable=False,
        ),
        "currency": sa.Column(
            "currency",
            sa.String(length=3),
            server_default="CNY",
            nullable=False,
        ),
        "sale_price": sa.Column("sale_price", sa.Float(), nullable=True),
    }
    existing_columns: dict[str, dict[str, Any]] = {}
    if not context.is_offline_mode():
        existing_columns = {
            column["name"]: column
            for column in sa.inspect(op.get_bind()).get_columns(
                "ecommerce_listing_tasks"
            )
        }
    for name, column in column_specs.items():
        if name not in existing_columns:
            op.add_column("ecommerce_listing_tasks", column)
    op.execute(
        """
        UPDATE ecommerce_listing_tasks
        SET sale_price = (
            SELECT price
            FROM ecommerce_products
            WHERE ecommerce_products.id = ecommerce_listing_tasks.product_id
        )
        WHERE sale_price IS NULL
        """
    )
    sale_price = existing_columns.get("sale_price")
    if sale_price is None or sale_price.get("nullable", True):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table("ecommerce_listing_tasks") as batch:
                batch.alter_column(
                    "sale_price",
                    existing_type=sa.Float(),
                    nullable=False,
                )
        else:
            op.alter_column(
                "ecommerce_listing_tasks",
                "sale_price",
                existing_type=sa.Float(),
                nullable=False,
            )


def downgrade() -> None:
    op.drop_column("ecommerce_listing_tasks", "sale_price")
    op.drop_column("ecommerce_listing_tasks", "currency")
    op.drop_column("ecommerce_listing_tasks", "locale")
    op.drop_column("ecommerce_listing_tasks", "market_code")
