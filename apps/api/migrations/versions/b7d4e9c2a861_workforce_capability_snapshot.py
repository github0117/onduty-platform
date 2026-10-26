"""workforce capability readiness snapshot

Revision ID: b7d4e9c2a861
Revises: f1a6d8c4b792
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "b7d4e9c2a861"
down_revision: str | None = "f1a6d8c4b792"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        "capability_snapshot_json": sa.Column(
            "capability_snapshot_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        "capability_assessed_at": sa.Column(
            "capability_assessed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    }
    existing_columns: set[str] = set()
    if not context.is_offline_mode():
        existing_columns = {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns(
                "workforce_tasks"
            )
        }
    for name, column in columns.items():
        if name not in existing_columns:
            op.add_column("workforce_tasks", column)


def downgrade() -> None:
    op.drop_column("workforce_tasks", "capability_assessed_at")
    op.drop_column("workforce_tasks", "capability_snapshot_json")
