"""agent skills and employee bindings

Revision ID: e8b1c4d2f901
Revises: d3a7f9c2e681
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b1c4d2f901"
down_revision: str | None = "d3a7f9c2e681"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("triggers_json", sa.JSON(), nullable=False),
        sa.Column("tools_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_agent_skill_business_code",
        ),
    )
    op.create_index(
        "ix_agent_skills_business_unit_id",
        "agent_skills",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_agent_skills_unit_status",
        "agent_skills",
        ["business_unit_id", "status"],
    )

    op.create_table(
        "digital_employee_skill_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["agent_skills.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "skill_id",
            name="uq_employee_skill_binding",
        ),
    )
    op.create_index(
        "ix_digital_employee_skill_bindings_employee_id",
        "digital_employee_skill_bindings",
        ["employee_id"],
    )
    op.create_index(
        "ix_digital_employee_skill_bindings_skill_id",
        "digital_employee_skill_bindings",
        ["skill_id"],
    )
    op.create_index(
        "ix_employee_skill_enabled_priority",
        "digital_employee_skill_bindings",
        ["employee_id", "enabled", "priority"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_skill_enabled_priority",
        table_name="digital_employee_skill_bindings",
    )
    op.drop_index(
        "ix_digital_employee_skill_bindings_skill_id",
        table_name="digital_employee_skill_bindings",
    )
    op.drop_index(
        "ix_digital_employee_skill_bindings_employee_id",
        table_name="digital_employee_skill_bindings",
    )
    op.drop_table("digital_employee_skill_bindings")
    op.drop_index("ix_agent_skills_unit_status", table_name="agent_skills")
    op.drop_index(
        "ix_agent_skills_business_unit_id",
        table_name="agent_skills",
    )
    op.drop_table("agent_skills")
