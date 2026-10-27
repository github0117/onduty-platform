"""knowledge reindex jobs and embedding index timestamp

Revision ID: c4d9e2f7a1b6
Revises: b8f2c7a41d63
Create Date: 2026-10-27 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c4d9e2f7a1b6"
down_revision: str | None = "b8f2c7a41d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_versions",
        sa.Column("embedding_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "knowledge_reindex_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("target_embedding_model", sa.String(length=160), nullable=False),
        sa.Column("target_chunking_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_versions", sa.Integer(), nullable=False),
        sa.Column("processed_versions", sa.Integer(), nullable=False),
        sa.Column("skipped_versions", sa.Integer(), nullable=False),
        sa.Column("failed_versions", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_reindex_jobs_unit_status",
        "knowledge_reindex_jobs",
        ["business_unit_id", "status"],
    )
    op.create_index(
        "ix_knowledge_reindex_jobs_document",
        "knowledge_reindex_jobs",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_reindex_jobs_document",
        table_name="knowledge_reindex_jobs",
    )
    op.drop_index(
        "ix_knowledge_reindex_jobs_unit_status",
        table_name="knowledge_reindex_jobs",
    )
    op.drop_table("knowledge_reindex_jobs")
    op.drop_column("knowledge_versions", "embedding_indexed_at")
