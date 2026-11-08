"""durable workflow runs and leased steps

Revision ID: b5e2a8d9c641
Revises: e1a7c4d90b62
Create Date: 2026-11-07 10:00:00.000000

Two tables back the retry/dead-letter engine:

* ``workflow_runs``: one row per outbox hand-off. The unique key on
  ``business_unit_id + workflow_type + idempotency_key`` makes a duplicated
  event resume the same run instead of starting a second one.
* ``workflow_steps``: leased unit of work. ``lease_expires_at`` lets the beat
  task recover steps claimed by a worker that died.

Additive only; no backfill is required or performed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e2a8d9c641"
down_revision: str | None = "e1a7c4d90b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("workflow_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "workflow_type",
            "idempotency_key",
            name="uq_workflow_run_idempotency",
        ),
    )
    op.create_index(
        "ix_workflow_runs_business_unit_id",
        "workflow_runs",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_workflow_runs_unit_status_created",
        "workflow_runs",
        ["business_unit_id", "status", "created_at"],
    )
    op.create_index(
        "ix_workflow_runs_aggregate_id",
        "workflow_runs",
        ["aggregate_id"],
    )
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name="fk_workflow_steps_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "name",
            name="uq_workflow_step_name",
        ),
    )
    op.create_index(
        "ix_workflow_steps_unit_status_available",
        "workflow_steps",
        ["business_unit_id", "status", "available_at"],
    )
    op.create_index(
        "ix_workflow_steps_run_created",
        "workflow_steps",
        ["workflow_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_steps_run_created", table_name="workflow_steps")
    op.drop_index(
        "ix_workflow_steps_unit_status_available",
        table_name="workflow_steps",
    )
    op.drop_table("workflow_steps")
    op.drop_index("ix_workflow_runs_aggregate_id", table_name="workflow_runs")
    op.drop_index(
        "ix_workflow_runs_unit_status_created",
        table_name="workflow_runs",
    )
    op.drop_index("ix_workflow_runs_business_unit_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
