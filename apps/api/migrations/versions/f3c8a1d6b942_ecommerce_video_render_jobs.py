"""ecommerce video render jobs

Revision ID: f3c8a1d6b942
Revises: d2f7a4c93e61
Create Date: 2026-10-23 20:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a1d6b942"
down_revision: str | None = "d2f7a4c93e61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ecommerce_video_render_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("listing_task_id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("source_asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("scene_count", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ecommerce_product_assets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["listing_task_id"],
            ["ecommerce_listing_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["ecommerce_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ecommerce_video_jobs_task_time",
        "ecommerce_video_render_jobs",
        ["listing_task_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_ecommerce_video_jobs_unit_status",
        "ecommerce_video_render_jobs",
        ["business_unit_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ecommerce_video_jobs_unit_status",
        table_name="ecommerce_video_render_jobs",
    )
    op.drop_index(
        "ix_ecommerce_video_jobs_task_time",
        table_name="ecommerce_video_render_jobs",
    )
    op.drop_table("ecommerce_video_render_jobs")
