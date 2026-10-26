"""embedding usage scope

Revision ID: d7f6e1a4c923
Revises: cbc91797877e
Create Date: 2026-10-23 14:20:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d7f6e1a4c923"
down_revision: str | None = "cbc91797877e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow system-owned model calls and scope them to a business unit."""
    with op.batch_alter_table("model_calls") as batch_op:
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("business_unit_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            "ix_model_calls_business_unit_id",
            ["business_unit_id"],
            unique=False,
        )


def downgrade() -> None:
    """Restore employee-owned model calls only."""
    with op.batch_alter_table("model_calls") as batch_op:
        batch_op.drop_index("ix_model_calls_business_unit_id")
        batch_op.drop_column("business_unit_id")
        batch_op.alter_column(
            "employee_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
