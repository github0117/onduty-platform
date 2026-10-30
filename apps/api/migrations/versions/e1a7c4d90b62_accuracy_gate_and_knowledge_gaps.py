"""accuracy gate verdict per turn and runtime knowledge-gap occurrences

Revision ID: e1a7c4d90b62
Revises: d9b2e5f7a1c4
Create Date: 2026-10-29 21:10:00.000000

The gate answers "may this reply leave without a human?" and must be frozen on
the turn, because auto-send and later audits read the verdict after the fact.

* ``conversation_turns.gate_json`` (nullable): decision, reasons and checks.
  NULL means "no verdict recorded"; readers treat it as not cleared for
  auto-send, so old rows fail closed instead of being grandfathered in.
* ``knowledge_gap_occurrences``: every question the published knowledge could
  not answer. A repair task opens only when the same normalized question
  recurs past the configured threshold, so the table is the evidence for the
  threshold rather than a per-question ticket machine.

Additive only; no backfill is required or performed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a7c4d90b62"
down_revision: str | None = "d9b2e5f7a1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_turns",
        sa.Column("gate_json", sa.JSON(), nullable=True),
    )
    op.create_table(
        "knowledge_gap_occurrences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("repair_task_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repair_task_id"],
            ["knowledge_repair_tasks.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_gap_occurrences_unit_query",
        "knowledge_gap_occurrences",
        ["business_unit_id", "normalized_query", "created_at"],
    )
    op.create_index(
        "ix_knowledge_gap_occurrences_created",
        "knowledge_gap_occurrences",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_gap_occurrences_created",
        table_name="knowledge_gap_occurrences",
    )
    op.drop_index(
        "ix_knowledge_gap_occurrences_unit_query",
        table_name="knowledge_gap_occurrences",
    )
    op.drop_table("knowledge_gap_occurrences")
    op.drop_column("conversation_turns", "gate_json")
