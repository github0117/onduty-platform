"""knowledge evaluation tuning and holdout datasets

Revision ID: f0b7a2c9d4e1
Revises: d5e1f8c2b903
Create Date: 2026-10-27 21:10:00.000000

Existing evaluation cases predate the tuning/holdout split and were the de
facto publish-gate set, so they are backfilled as HOLDOUT to keep gate
behaviour unchanged. New cases default to TUNING; holdout cases are frozen.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f0b7a2c9d4e1"
down_revision: str | None = "d5e1f8c2b903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_evaluation_cases",
        sa.Column(
            "dataset",
            sa.String(16),
            nullable=False,
            server_default="TUNING",
        ),
    )
    for column in (
        "expected_chunk_ids_json",
        "expected_document_ids_json",
        "negative_document_ids_json",
    ):
        op.add_column(
            "knowledge_evaluation_cases",
            sa.Column(
                column,
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    op.execute(
        "UPDATE knowledge_evaluation_cases SET dataset = 'HOLDOUT'"
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column(
            "dataset",
            sa.String(16),
            nullable=False,
            server_default="TUNING",
        ),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("chunk_recall_at_k", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("chunk_mrr", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("document_recall_at_k", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("document_mrr", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("context_precision", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("negative_violation_rate", sa.Float(), nullable=True),
    )
    op.add_column(
        "knowledge_evaluation_runs",
        sa.Column("baseline_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    for column in (
        "baseline_json",
        "negative_violation_rate",
        "context_precision",
        "document_mrr",
        "document_recall_at_k",
        "chunk_mrr",
        "chunk_recall_at_k",
        "dataset",
    ):
        op.drop_column("knowledge_evaluation_runs", column)
    for column in (
        "negative_document_ids_json",
        "expected_document_ids_json",
        "expected_chunk_ids_json",
        "dataset",
    ):
        op.drop_column("knowledge_evaluation_cases", column)
