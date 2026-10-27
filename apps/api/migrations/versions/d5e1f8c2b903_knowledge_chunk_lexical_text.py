"""knowledge chunk lexical text for hybrid retrieval

Revision ID: d5e1f8c2b903
Revises: c4d9e2f7a1b6
Create Date: 2026-10-27 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d5e1f8c2b903"
down_revision: str | None = "c4d9e2f7a1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEXICAL_INDEX = "ix_knowledge_chunks_lexical"


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column("lexical_text", sa.Text(), nullable=True),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            f"CREATE INDEX {LEXICAL_INDEX} ON knowledge_chunks "
            "USING gin (to_tsvector('simple', coalesce(lexical_text, '')))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {LEXICAL_INDEX}")
    op.drop_column("knowledge_chunks", "lexical_text")
