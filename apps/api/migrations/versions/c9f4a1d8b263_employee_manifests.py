"""employee manifests and revisions

Revision ID: c9f4a1d8b263
Revises: b3e6f9d1c842
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f4a1d8b263"
down_revision: str | None = "b3e6f9d1c842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "digital_employees",
        sa.Column(
            "domain",
            sa.String(length=64),
            nullable=False,
            server_default="customer_service",
        ),
    )
    op.add_column(
        "digital_employees",
        sa.Column("template_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "digital_employees",
        sa.Column(
            "manifest_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "digital_employees",
        sa.Column(
            "config_revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_table(
        "digital_employee_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "revision",
            name="uq_digital_employee_revision",
        ),
    )
    op.create_index(
        "ix_digital_employee_revisions_employee_id",
        "digital_employee_revisions",
        ["employee_id"],
    )
    op.create_index(
        "ix_employee_revisions_employee_time",
        "digital_employee_revisions",
        ["employee_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_revisions_employee_time",
        table_name="digital_employee_revisions",
    )
    op.drop_index(
        "ix_digital_employee_revisions_employee_id",
        table_name="digital_employee_revisions",
    )
    op.drop_table("digital_employee_revisions")
    op.drop_column("digital_employees", "config_revision")
    op.drop_column("digital_employees", "manifest_json")
    op.drop_column("digital_employees", "template_code")
    op.drop_column("digital_employees", "domain")
