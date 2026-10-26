"""template resource snapshots and trial activation

Revision ID: e2a7c9d1f643
Revises: d9f6b2c4e813
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "e2a7c9d1f643"
down_revision: str | None = "d9f6b2c4e813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    specifications = {
        "digital_employees": {
            "activation_evaluation_json": sa.Column(
                "activation_evaluation_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            "activation_evaluated_at": sa.Column(
                "activation_evaluated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        },
        "digital_employee_templates": {
            "knowledge_bindings_json": sa.Column(
                "knowledge_bindings_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            "mcp_bindings_json": sa.Column(
                "mcp_bindings_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            "model_profile_json": sa.Column(
                "model_profile_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            "knowledge_policy_json": sa.Column(
                "knowledge_policy_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            "readiness_snapshot_json": sa.Column(
                "readiness_snapshot_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        },
    }
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    for table_name, columns in specifications.items():
        existing_columns = (
            {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            if inspector is not None
            else set()
        )
        for name, column in columns.items():
            if name not in existing_columns:
                op.add_column(table_name, column)
    unique_constraints = (
        {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "digital_employee_templates"
            )
        }
        if inspector is not None
        else set()
    )
    if (
        inspector is None
        or "uq_employee_template_source_draft" not in unique_constraints
    ):
        if (
            inspector is None
            or op.get_bind().dialect.name == "sqlite"
        ):
            with op.batch_alter_table(
                "digital_employee_templates"
            ) as batch:
                batch.create_unique_constraint(
                    "uq_employee_template_source_draft",
                    ["source_draft_id"],
                )
        else:
            op.create_unique_constraint(
                "uq_employee_template_source_draft",
                "digital_employee_templates",
                ["source_draft_id"],
            )


def downgrade() -> None:
    op.drop_constraint(
        "uq_employee_template_source_draft",
        "digital_employee_templates",
        type_="unique",
    )
    op.drop_column(
        "digital_employee_templates",
        "readiness_snapshot_json",
    )
    op.drop_column(
        "digital_employee_templates",
        "knowledge_policy_json",
    )
    op.drop_column("digital_employee_templates", "model_profile_json")
    op.drop_column("digital_employee_templates", "mcp_bindings_json")
    op.drop_column(
        "digital_employee_templates",
        "knowledge_bindings_json",
    )
    op.drop_column("digital_employees", "activation_evaluated_at")
    op.drop_column("digital_employees", "activation_evaluation_json")
