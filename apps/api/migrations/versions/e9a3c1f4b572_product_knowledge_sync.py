"""product knowledge sync metadata

Revision ID: e9a3c1f4b572
Revises: d8f4a1c9e672
Create Date: 2026-10-24 19:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "e9a3c1f4b572"
down_revision: str | None = "d8f4a1c9e672"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        "source_type": sa.Column(
            "source_type",
            sa.String(length=64),
            nullable=True,
        ),
        "source_ref": sa.Column(
            "source_ref",
            sa.String(length=200),
            nullable=True,
        ),
        "source_version": sa.Column(
            "source_version",
            sa.String(length=64),
            nullable=True,
        ),
        "sync_status": sa.Column(
            "sync_status",
            sa.String(length=24),
            nullable=True,
        ),
        "last_synced_at": sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    }
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    existing_columns = (
        {
            column["name"]
            for column in inspector.get_columns("knowledge_documents")
        }
        if inspector is not None
        else set()
    )
    for name, column in columns.items():
        if name not in existing_columns:
            op.add_column("knowledge_documents", column)
    unique_constraints = (
        {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "knowledge_documents"
            )
        }
        if inspector is not None
        else set()
    )
    if (
        inspector is None
        or "uq_knowledge_document_source" not in unique_constraints
    ):
        if (
            inspector is None
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "knowledge_documents"
            ) as batch:
                batch.create_unique_constraint(
                    "uq_knowledge_document_source",
                    [
                        "business_unit_id",
                        "source_type",
                        "source_ref",
                    ],
                )
        else:
            op.create_unique_constraint(
                "uq_knowledge_document_source",
                "knowledge_documents",
                ["business_unit_id", "source_type", "source_ref"],
            )
    indexes = (
        {
            index["name"]
            for index in inspector.get_indexes("knowledge_documents")
        }
        if inspector is not None
        else set()
    )
    if inspector is None or "ix_knowledge_documents_sync" not in indexes:
        op.create_index(
            "ix_knowledge_documents_sync",
            "knowledge_documents",
            ["business_unit_id", "source_type", "sync_status"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_documents_sync",
        table_name="knowledge_documents",
    )
    op.drop_constraint(
        "uq_knowledge_document_source",
        "knowledge_documents",
        type_="unique",
    )
    op.drop_column("knowledge_documents", "last_synced_at")
    op.drop_column("knowledge_documents", "sync_status")
    op.drop_column("knowledge_documents", "source_version")
    op.drop_column("knowledge_documents", "source_ref")
    op.drop_column("knowledge_documents", "source_type")
