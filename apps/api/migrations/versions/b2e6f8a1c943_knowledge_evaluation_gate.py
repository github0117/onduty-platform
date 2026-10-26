"""knowledge evaluation publish gate

Revision ID: b2e6f8a1c943
Revises: a7d1c4e9f632
Create Date: 2026-10-24 20:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b2e6f8a1c943"
down_revision: str | None = "a7d1c4e9f632"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_spaces",
        sa.Column(
            "evaluation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_spaces", "evaluation_required")
