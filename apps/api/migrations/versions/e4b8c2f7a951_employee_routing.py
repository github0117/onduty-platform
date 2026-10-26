"""digital employee routing rules and decisions

Revision ID: e4b8c2f7a951
Revises: d2e7b4c9a351
Create Date: 2026-10-24
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "e4b8c2f7a951"
down_revision: str | None = "d2e7b4c9a351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digital_employee_route_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("intents_json", sa.JSON(), nullable=False),
        sa.Column("categories_json", sa.JSON(), nullable=False),
        sa.Column("channels_json", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("fallback", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            name="uq_digital_employee_route_rule",
        ),
    )
    op.create_index(
        "ix_digital_employee_route_rules_business_unit_id",
        "digital_employee_route_rules",
        ["business_unit_id"],
    )
    op.create_index(
        "ix_digital_employee_route_rules_employee_id",
        "digital_employee_route_rules",
        ["employee_id"],
    )
    connection = op.get_bind()
    employees = connection.execute(
        sa.text(
            """
            SELECT e.id, e.business_unit_id, e.manifest_json,
                   e.template_code, e.created_at
            FROM digital_employees e
            LEFT JOIN digital_employee_route_rules r
              ON r.employee_id = e.id
            WHERE r.id IS NULL
            """
        )
    ).mappings()
    for employee in employees:
        manifest = employee["manifest_json"] or {}
        intents = (
            manifest.get("intents", [])
            if isinstance(manifest, dict)
            else []
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO digital_employee_route_rules (
                    id, business_unit_id, employee_id, intents_json,
                    categories_json, channels_json, priority, fallback,
                    enabled, created_at, updated_at
                ) VALUES (
                    :id, :business_unit_id, :employee_id,
                    CAST(:intents_json AS JSON), CAST(:categories_json AS JSON),
                    CAST(:channels_json AS JSON), :priority, :fallback,
                    TRUE, :created_at, :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "business_unit_id": employee["business_unit_id"],
                "employee_id": str(employee["id"]),
                "intents_json": json.dumps(
                    intents,
                    ensure_ascii=False,
                ),
                "categories_json": "[]",
                "channels_json": "[]",
                "priority": 100,
                "fallback": employee["template_code"] is None,
                "created_at": employee["created_at"] or datetime.now(UTC),
                "updated_at": employee["created_at"] or datetime.now(UTC),
            },
        )

    op.create_table(
        "digital_employee_route_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("selected_employee_id", sa.Uuid(), nullable=False),
        sa.Column("selected_employee_key", sa.String(length=100), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employee_route_decisions_unit_time",
        "digital_employee_route_decisions",
        ["business_unit_id", "created_at"],
    )
    op.create_index(
        "ix_employee_route_decisions_ticket",
        "digital_employee_route_decisions",
        ["ticket_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_route_decisions_ticket",
        table_name="digital_employee_route_decisions",
    )
    op.drop_index(
        "ix_employee_route_decisions_unit_time",
        table_name="digital_employee_route_decisions",
    )
    op.drop_table("digital_employee_route_decisions")
    op.drop_index(
        "ix_digital_employee_route_rules_employee_id",
        table_name="digital_employee_route_rules",
    )
    op.drop_index(
        "ix_digital_employee_route_rules_business_unit_id",
        table_name="digital_employee_route_rules",
    )
    op.drop_table("digital_employee_route_rules")
