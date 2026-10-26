"""add digital employee ownership to ecommerce work

Revision ID: e4b8c2d6f135
Revises: d7a3f1c9b624
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "e4b8c2d6f135"
down_revision: str | None = "d7a3f1c9b624"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    specifications = (
        (
            "ecommerce_listing_tasks",
            "fk_ecommerce_listing_owner_employee",
        ),
        (
            "ecommerce_product_assets",
            "fk_ecommerce_asset_owner_employee",
        ),
    )
    for table_name, foreign_key_name in specifications:
        columns = (
            {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            if inspector is not None
            else set()
        )
        if inspector is None or "owner_employee_id" not in columns:
            op.add_column(
                table_name,
                sa.Column("owner_employee_id", sa.Uuid(), nullable=True),
            )
        foreign_keys = (
            list(inspector.get_foreign_keys(table_name))
            if inspector is not None
            else []
        )
        has_foreign_key = any(
            foreign_key.get("name") == foreign_key_name
            or foreign_key.get("constrained_columns")
            == ["owner_employee_id"]
            for foreign_key in foreign_keys
        )
        if inspector is None or not has_foreign_key:
            if (
                inspector is None
                or op.get_bind().dialect.name == "sqlite"
            ):
                with op.batch_alter_table(table_name) as batch:
                    batch.create_foreign_key(
                        foreign_key_name,
                        "digital_employees",
                        ["owner_employee_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.create_foreign_key(
                    foreign_key_name,
                    table_name,
                    "digital_employees",
                    ["owner_employee_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ecommerce_asset_owner_employee",
        "ecommerce_product_assets",
        type_="foreignkey",
    )
    op.drop_column("ecommerce_product_assets", "owner_employee_id")
    op.drop_constraint(
        "fk_ecommerce_listing_owner_employee",
        "ecommerce_listing_tasks",
        type_="foreignkey",
    )
    op.drop_column("ecommerce_listing_tasks", "owner_employee_id")
