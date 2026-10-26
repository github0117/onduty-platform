"""add business service entries

Revision ID: d7a3f1c9b624
Revises: c8f2a4d7e910
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "d7a3f1c9b624"
down_revision: str | None = "c8f2a4d7e910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    if (
        inspector is None
        or not inspector.has_table("business_service_entries")
    ):
        op.create_table(
            "business_service_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_unit_id", sa.String(64), nullable=False),
            sa.Column("code", sa.String(100), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(64), nullable=False),
            sa.Column("channel", sa.String(64), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("default_employee_id", sa.Uuid(), nullable=True),
            sa.Column("fallback_employee_id", sa.Uuid(), nullable=True),
            sa.Column("human_queue_id", sa.String(64), nullable=False),
            sa.Column("knowledge_scope_json", sa.JSON(), nullable=False),
            sa.Column("sla_policy_json", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["default_employee_id"],
                ["digital_employees.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["fallback_employee_id"],
                ["digital_employees.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_unit_id",
                "code",
                name="uq_business_service_entry_unit_code",
            ),
        )
    entry_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes("business_service_entries")
        }
        if inspector is not None
        and inspector.has_table("business_service_entries")
        else set()
    )
    if (
        inspector is None
        or "ix_business_service_entries_unit_status" not in entry_indexes
    ):
        op.create_index(
            "ix_business_service_entries_unit_status",
            "business_service_entries",
            ["business_unit_id", "status"],
        )
    if (
        inspector is None
        or not inspector.has_table("business_service_entry_employees")
    ):
        op.create_table(
            "business_service_entry_employees",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("service_entry_id", sa.Uuid(), nullable=False),
            sa.Column("employee_id", sa.Uuid(), nullable=False),
            sa.Column("role_type", sa.String(24), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["employee_id"],
                ["digital_employees.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["service_entry_id"],
                ["business_service_entries.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "service_entry_id",
                "employee_id",
                name="uq_business_service_entry_employee",
            ),
        )
    employee_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes(
                "business_service_entry_employees"
            )
        }
        if inspector is not None
        and inspector.has_table("business_service_entry_employees")
        else set()
    )
    if (
        inspector is None
        or "ix_business_entry_employees_entry_enabled"
        not in employee_indexes
    ):
        op.create_index(
            "ix_business_entry_employees_entry_enabled",
            "business_service_entry_employees",
            ["service_entry_id", "enabled"],
        )
    conversation_columns = (
        {
            column["name"]
            for column in inspector.get_columns("customer_conversations")
        }
        if inspector is not None
        else set()
    )
    if inspector is None or "service_entry_id" not in conversation_columns:
        op.add_column(
            "customer_conversations",
            sa.Column("service_entry_id", sa.Uuid(), nullable=True),
        )
    conversation_foreign_keys = (
        list(inspector.get_foreign_keys("customer_conversations"))
        if inspector is not None
        else []
    )
    has_service_entry_foreign_key = any(
        foreign_key.get("name")
        == "fk_customer_conversations_service_entry"
        or foreign_key.get("constrained_columns") == ["service_entry_id"]
        for foreign_key in conversation_foreign_keys
    )
    if inspector is None or not has_service_entry_foreign_key:
        if (
            inspector is None
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "customer_conversations"
            ) as batch:
                batch.create_foreign_key(
                    "fk_customer_conversations_service_entry",
                    "business_service_entries",
                    ["service_entry_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                "fk_customer_conversations_service_entry",
                "customer_conversations",
                "business_service_entries",
                ["service_entry_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_customer_conversations_service_entry",
        "customer_conversations",
        type_="foreignkey",
    )
    op.drop_column("customer_conversations", "service_entry_id")
    op.drop_index(
        "ix_business_entry_employees_entry_enabled",
        table_name="business_service_entry_employees",
    )
    op.drop_table("business_service_entry_employees")
    op.drop_index(
        "ix_business_service_entries_unit_status",
        table_name="business_service_entries",
    )
    op.drop_table("business_service_entries")
