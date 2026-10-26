"""managed employee templates

Revision ID: d9f6b2c4e813
Revises: c8e5f1a7d942
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "d9f6b2c4e813"
down_revision: str | None = "c8e5f1a7d942"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    if (
        inspector is None
        or not inspector.has_table("digital_employee_templates")
    ):
        op.create_table(
            "digital_employee_templates",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("business_unit_id", sa.String(length=64), nullable=False),
            sa.Column("code", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("domain", sa.String(length=64), nullable=False),
            sa.Column("workflow_key", sa.String(length=100), nullable=False),
            sa.Column("scenario_type", sa.String(length=64), nullable=False),
            sa.Column("handoff_queue", sa.String(length=64), nullable=False),
            sa.Column("capabilities_json", sa.JSON(), nullable=False),
            sa.Column("intents_json", sa.JSON(), nullable=False),
            sa.Column("skill_codes_json", sa.JSON(), nullable=False),
            sa.Column("tool_allowlist_json", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("source_draft_id", sa.Uuid(), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=128), nullable=False),
            sa.Column("reviewed_by", sa.String(length=128), nullable=True),
            sa.Column(
                "reviewed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "disabled_at",
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
                ["source_draft_id"],
                ["digital_employee_drafts.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "business_unit_id",
                "code",
                name="uq_digital_employee_template_code",
            ),
        )
    template_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes(
                "digital_employee_templates"
            )
        }
        if inspector is not None
        and inspector.has_table("digital_employee_templates")
        else set()
    )
    if (
        inspector is None
        or "ix_employee_templates_unit_status" not in template_indexes
    ):
        op.create_index(
            "ix_employee_templates_unit_status",
            "digital_employee_templates",
            ["business_unit_id", "status", "created_at"],
        )
    draft_columns = (
        {
            column["name"]
            for column in inspector.get_columns("digital_employee_drafts")
        }
        if inspector is not None
        else set()
    )
    if inspector is None or "promoted_template_id" not in draft_columns:
        op.add_column(
            "digital_employee_drafts",
            sa.Column("promoted_template_id", sa.Uuid(), nullable=True),
        )
    draft_foreign_keys = (
        list(inspector.get_foreign_keys("digital_employee_drafts"))
        if inspector is not None
        else []
    )
    has_template_foreign_key = any(
        foreign_key.get("name")
        == "fk_employee_draft_promoted_template"
        or foreign_key.get("constrained_columns")
        == ["promoted_template_id"]
        for foreign_key in draft_foreign_keys
    )
    if inspector is None or not has_template_foreign_key:
        if (
            inspector is None
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "digital_employee_drafts"
            ) as batch:
                batch.create_foreign_key(
                    "fk_employee_draft_promoted_template",
                    "digital_employee_templates",
                    ["promoted_template_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                "fk_employee_draft_promoted_template",
                "digital_employee_drafts",
                "digital_employee_templates",
                ["promoted_template_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    op.drop_constraint(
        "fk_employee_draft_promoted_template",
        "digital_employee_drafts",
        type_="foreignkey",
    )
    op.drop_column("digital_employee_drafts", "promoted_template_id")
    op.drop_index(
        "ix_employee_templates_unit_status",
        table_name="digital_employee_templates",
    )
    op.drop_table("digital_employee_templates")
