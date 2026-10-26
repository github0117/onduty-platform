"""digital employee drafts lifecycle

Revision ID: c8e5f1a7d942
Revises: b7d4e9c2a861
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e5f1a7d942"
down_revision: str | None = "b7d4e9c2a861"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_employee_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("source_task_id", sa.Uuid(), nullable=True),
        sa.Column("source_step_id", sa.Uuid(), nullable=True),
        sa.Column(
            "required_capability",
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("template_code", sa.String(length=100), nullable=True),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("workflow_key", sa.String(length=100), nullable=False),
        sa.Column("scenario_type", sa.String(length=64), nullable=False),
        sa.Column("handoff_queue", sa.String(length=64), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("intents_json", sa.JSON(), nullable=False),
        sa.Column("skill_codes_json", sa.JSON(), nullable=False),
        sa.Column("tool_allowlist_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_json", sa.JSON(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "rolled_back_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_task_id"],
            ["workforce_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_task_id",
            "required_capability",
            name="uq_employee_draft_task_capability",
        ),
    )
    op.create_index(
        "ix_employee_drafts_unit_status",
        "digital_employee_drafts",
        ["business_unit_id", "status", "created_at"],
    )
    op.create_index(
        "ix_digital_employee_drafts_source_task_id",
        "digital_employee_drafts",
        ["source_task_id"],
    )
    op.create_index(
        "ix_digital_employee_drafts_employee_id",
        "digital_employee_drafts",
        ["employee_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_digital_employee_drafts_employee_id",
        table_name="digital_employee_drafts",
    )
    op.drop_index(
        "ix_digital_employee_drafts_source_task_id",
        table_name="digital_employee_drafts",
    )
    op.drop_index(
        "ix_employee_drafts_unit_status",
        table_name="digital_employee_drafts",
    )
    op.drop_table("digital_employee_drafts")
