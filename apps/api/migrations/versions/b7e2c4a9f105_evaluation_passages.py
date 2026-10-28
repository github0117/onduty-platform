"""knowledge evaluation passage expectations

Revision ID: b7e2c4a9f105
Revises: f0b7a2c9d4e1
Create Date: 2026-10-28 10:10:00.000000

Evaluation cases used to point at chunk UUIDs, so every reindex (which
replaces chunk rows) invalidated them. Passage expectations store the
document id plus the original text and are resolved to chunks at run time.
Existing cases keep their chunk ids and behave exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b7e2c4a9f105"
down_revision: str | None = "f0b7a2c9d4e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_evaluation_cases",
        sa.Column(
            "expected_passages_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_evaluation_cases", "expected_passages_json")
