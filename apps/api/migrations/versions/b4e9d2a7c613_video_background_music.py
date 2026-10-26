"""video background music

Revision ID: b4e9d2a7c613
Revises: a1d7c4e9b205
Create Date: 2026-10-24 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "b4e9d2a7c613"
down_revision: str | None = "a1d7c4e9b205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        "background_music_asset_id": sa.Column(
            "background_music_asset_id",
            sa.Uuid(),
            nullable=True,
        ),
        "background_music_volume": sa.Column(
            "background_music_volume",
            sa.Float(),
            server_default="0.18",
            nullable=False,
        ),
    }
    existing_columns: set[str] = set()
    existing_foreign_keys: list[dict[str, object]] = []
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        existing_columns = {
            column["name"]
            for column in inspector.get_columns(
                "ecommerce_video_render_jobs"
            )
        }
        existing_foreign_keys = list(
            inspector.get_foreign_keys("ecommerce_video_render_jobs")
        )
    for name, column in columns.items():
        if name not in existing_columns:
            op.add_column("ecommerce_video_render_jobs", column)
    has_music_foreign_key = any(
        foreign_key.get("name")
        == "fk_ecommerce_video_jobs_background_music"
        or foreign_key.get("constrained_columns")
        == ["background_music_asset_id"]
        for foreign_key in existing_foreign_keys
    )
    if context.is_offline_mode() or not has_music_foreign_key:
        if (
            context.is_offline_mode()
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "ecommerce_video_render_jobs"
            ) as batch:
                batch.create_foreign_key(
                    "fk_ecommerce_video_jobs_background_music",
                    "ecommerce_product_assets",
                    ["background_music_asset_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                "fk_ecommerce_video_jobs_background_music",
                "ecommerce_video_render_jobs",
                "ecommerce_product_assets",
                ["background_music_asset_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ecommerce_video_jobs_background_music",
        "ecommerce_video_render_jobs",
        type_="foreignkey",
    )
    op.drop_column("ecommerce_video_render_jobs", "background_music_volume")
    op.drop_column("ecommerce_video_render_jobs", "background_music_asset_id")
