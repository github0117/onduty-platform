"""managed template revisions

Revision ID: f4b8d1c6e925
Revises: e2a7c9d1f643
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op

revision: str = "f4b8d1c6e925"
down_revision: str | None = "e2a7c9d1f643"
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
        or not inspector.has_table("digital_employee_template_revisions")
    ):
        op.create_table(
            "digital_employee_template_revisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("template_id", sa.Uuid(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("change_note", sa.String(length=500), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=False),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["template_id"],
                ["digital_employee_templates.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "template_id",
                "revision",
                name="uq_employee_template_revision",
            ),
        )
    revision_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes(
                "digital_employee_template_revisions"
            )
        }
        if inspector is not None
        and inspector.has_table("digital_employee_template_revisions")
        else set()
    )
    if (
        inspector is None
        or "ix_employee_template_revisions_template_time"
        not in revision_indexes
    ):
        op.create_index(
            "ix_employee_template_revisions_template_time",
            "digital_employee_template_revisions",
            ["template_id", "created_at"],
        )
    bind = op.get_bind()
    revisions = sa.table(
        "digital_employee_template_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("template_id", sa.Uuid()),
        sa.column("revision", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("snapshot_json", sa.JSON()),
        sa.column("change_note", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    templates = sa.table(
        "digital_employee_templates",
        sa.column("id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for template in bind.execute(sa.select(templates)).mappings():
        existing_revision = bind.execute(
            sa.select(revisions.c.id).where(
                revisions.c.template_id == template["id"],
                revisions.c.revision == template["version"],
            )
        ).scalar()
        if existing_revision is not None:
            continue
        bind.execute(
            revisions.insert().values(
                id=uuid4(),
                template_id=template["id"],
                revision=template["version"],
                status=template["status"],
                snapshot_json={},
                change_note="Backfilled current template state",
                created_by=template["created_by"],
                published_at=template["published_at"],
                created_at=template["created_at"],
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_template_revisions_template_time",
        table_name="digital_employee_template_revisions",
    )
    op.drop_table("digital_employee_template_revisions")
