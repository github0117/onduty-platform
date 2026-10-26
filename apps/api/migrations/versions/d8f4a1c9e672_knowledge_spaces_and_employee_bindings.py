"""knowledge spaces and employee bindings

Revision ID: d8f4a1c9e672
Revises: c7d1e5b9a824
Create Date: 2026-10-24 18:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "d8f4a1c9e672"
down_revision: str | None = "c7d1e5b9a824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    if inspector is None or not inspector.has_table("knowledge_spaces"):
        op.create_table(
            "knowledge_spaces",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_unit_id", sa.String(length=64), nullable=False),
            sa.Column("code", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(length=64), nullable=False),
            sa.Column("channel", sa.String(length=64), nullable=True),
            sa.Column("category", sa.String(length=128), nullable=True),
            sa.Column("workflow_key", sa.String(length=100), nullable=True),
            sa.Column("owner_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_unit_id",
                "code",
                name="uq_knowledge_space_business_code",
            ),
        )
    space_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes("knowledge_spaces")
        }
        if inspector is not None
        and inspector.has_table("knowledge_spaces")
        else set()
    )
    if (
        inspector is None
        or "ix_knowledge_spaces_unit_status" not in space_indexes
    ):
        op.create_index(
            "ix_knowledge_spaces_unit_status",
            "knowledge_spaces",
            ["business_unit_id", "status"],
            unique=False,
        )

    document_columns = (
        {
            column["name"]
            for column in inspector.get_columns("knowledge_documents")
        }
        if inspector is not None
        else set()
    )
    if inspector is None or "space_id" not in document_columns:
        op.add_column(
            "knowledge_documents",
            sa.Column("space_id", sa.Uuid(), nullable=True),
        )
    document_foreign_keys = (
        list(inspector.get_foreign_keys("knowledge_documents"))
        if inspector is not None
        else []
    )
    has_document_foreign_key = any(
        foreign_key.get("name") == "fk_knowledge_documents_space_id"
        or foreign_key.get("constrained_columns") == ["space_id"]
        for foreign_key in document_foreign_keys
    )
    if inspector is None or not has_document_foreign_key:
        if (
            inspector is None
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "knowledge_documents"
            ) as batch:
                batch.create_foreign_key(
                    "fk_knowledge_documents_space_id",
                    "knowledge_spaces",
                    ["space_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                "fk_knowledge_documents_space_id",
                "knowledge_documents",
                "knowledge_spaces",
                ["space_id"],
                ["id"],
                ondelete="SET NULL",
            )
    document_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes("knowledge_documents")
        }
        if inspector is not None
        else set()
    )
    if (
        inspector is None
        or "ix_knowledge_documents_space" not in document_indexes
    ):
        op.create_index(
            "ix_knowledge_documents_space",
            "knowledge_documents",
            ["space_id", "status"],
            unique=False,
        )

    if (
        inspector is None
        or not inspector.has_table("digital_employee_knowledge_bindings")
    ):
        op.create_table(
            "digital_employee_knowledge_bindings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("employee_id", sa.Uuid(), nullable=False),
            sa.Column("knowledge_space_id", sa.Uuid(), nullable=False),
            sa.Column("workflow_key", sa.String(length=100), nullable=True),
            sa.Column("scope_json", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["employee_id"],
                ["digital_employees.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["knowledge_space_id"],
                ["knowledge_spaces.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "employee_id",
                "knowledge_space_id",
                "workflow_key",
                name="uq_employee_knowledge_binding",
            ),
        )
    binding_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes(
                "digital_employee_knowledge_bindings"
            )
        }
        if inspector is not None
        and inspector.has_table("digital_employee_knowledge_bindings")
        else set()
    )
    if (
        inspector is None
        or "ix_employee_knowledge_bindings_employee" not in binding_indexes
    ):
        op.create_index(
            "ix_employee_knowledge_bindings_employee",
            "digital_employee_knowledge_bindings",
            ["employee_id", "enabled"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_knowledge_bindings_employee",
        table_name="digital_employee_knowledge_bindings",
    )
    op.drop_table("digital_employee_knowledge_bindings")
    op.drop_index(
        "ix_knowledge_documents_space",
        table_name="knowledge_documents",
    )
    op.drop_constraint(
        "fk_knowledge_documents_space_id",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_column("knowledge_documents", "space_id")
    op.drop_index(
        "ix_knowledge_spaces_unit_status",
        table_name="knowledge_spaces",
    )
    op.drop_table("knowledge_spaces")
