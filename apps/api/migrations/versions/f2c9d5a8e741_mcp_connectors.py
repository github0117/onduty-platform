"""mcp connectors and employee bindings

Revision ID: f2c9d5a8e741
Revises: e8b1c4d2f901
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c9d5a8e741"
down_revision: str | None = "e8b1c4d2f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("header_env_json", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_mcp_connector_business_code",
        ),
    )
    op.create_index(
        "ix_mcp_connectors_business_unit_id",
        "mcp_connectors",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_mcp_connectors_unit_status",
        "mcp_connectors",
        ["business_unit_id", "status"],
    )

    op.create_table(
        "digital_employee_mcp_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_tools_json", sa.JSON(), nullable=False),
        sa.Column("write_approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["mcp_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "connector_id",
            name="uq_employee_mcp_connector",
        ),
    )
    op.create_index(
        "ix_digital_employee_mcp_bindings_connector_id",
        "digital_employee_mcp_bindings",
        ["connector_id"],
    )
    op.create_index(
        "ix_digital_employee_mcp_bindings_employee_id",
        "digital_employee_mcp_bindings",
        ["employee_id"],
    )
    op.create_index(
        "ix_employee_mcp_enabled",
        "digital_employee_mcp_bindings",
        ["employee_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_mcp_enabled",
        table_name="digital_employee_mcp_bindings",
    )
    op.drop_index(
        "ix_digital_employee_mcp_bindings_employee_id",
        table_name="digital_employee_mcp_bindings",
    )
    op.drop_index(
        "ix_digital_employee_mcp_bindings_connector_id",
        table_name="digital_employee_mcp_bindings",
    )
    op.drop_table("digital_employee_mcp_bindings")
    op.drop_index("ix_mcp_connectors_unit_status", table_name="mcp_connectors")
    op.drop_index(
        "ix_mcp_connectors_business_unit_id",
        table_name="mcp_connectors",
    )
    op.drop_table("mcp_connectors")
