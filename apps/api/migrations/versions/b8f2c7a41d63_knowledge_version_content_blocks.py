"""knowledge version structured content blocks

Revision ID: b8f2c7a41d63
Revises: e7a1c3d5b9f2
Create Date: 2026-10-27 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b8f2c7a41d63"
down_revision: str | None = "e7a1c3d5b9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_versions",
        sa.Column("content_blocks_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_versions", "content_blocks_json")
