"""knowledge retrieval evaluation

Revision ID: f4c2d8e9a731
Revises: e9a3c1f4b572
Create Date: 2026-10-24 19:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f4c2d8e9a731"
down_revision: str | None = "e9a3c1f4b572"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_evaluation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_space_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_titles_json", sa.JSON(), nullable=False),
        sa.Column("expect_no_grounding", sa.Boolean(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_space_id"],
            ["knowledge_spaces.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_evaluation_cases_unit_enabled",
        "knowledge_evaluation_cases",
        ["business_unit_id", "enabled"],
        unique=False,
    )
    op.create_table(
        "knowledge_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("failed_cases", sa.Integer(), nullable=False),
        sa.Column("recall_at_k", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("no_grounding_accuracy", sa.Float(), nullable=True),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_evaluation_runs_unit_time",
        "knowledge_evaluation_runs",
        ["business_unit_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_evaluation_runs_unit_time",
        table_name="knowledge_evaluation_runs",
    )
    op.drop_table("knowledge_evaluation_runs")
    op.drop_index(
        "ix_knowledge_evaluation_cases_unit_enabled",
        table_name="knowledge_evaluation_cases",
    )
    op.drop_table("knowledge_evaluation_cases")
