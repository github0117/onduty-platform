"""ecommerce listing batch jobs

Revision ID: c7d1e5b9a824
Revises: b4e9d2a7c613
Create Date: 2026-10-24 16:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c7d1e5b9a824"
down_revision: str | None = "b4e9d2a7c613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_listing_batch_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("market_code", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_listing_batches_unit_time",
        "ecommerce_listing_batch_jobs",
        ["business_unit_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "ecommerce_listing_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_job_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("listing_task_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_job_id"],
            ["ecommerce_listing_batch_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["listing_task_id"],
            ["ecommerce_listing_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["ecommerce_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_listing_batch_items_job",
        "ecommerce_listing_batch_items",
        ["batch_job_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_listing_batch_items_job",
        table_name="ecommerce_listing_batch_items",
    )
    op.drop_table("ecommerce_listing_batch_items")
    op.drop_index(
        "ix_ecommerce_listing_batches_unit_time",
        table_name="ecommerce_listing_batch_jobs",
    )
    op.drop_table("ecommerce_listing_batch_jobs")
