"""employee draft revisions

Revision ID: a5c9e2f7d831
Revises: f4b8d1c6e925
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import context, op

revision: str = "a5c9e2f7d831"
down_revision: str | None = "f4b8d1c6e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = (
        None
        if context.is_offline_mode()
        else sa.inspect(op.get_bind())
    )
    draft_columns = (
        {
            column["name"]
            for column in inspector.get_columns("digital_employee_drafts")
        }
        if inspector is not None
        else set()
    )
    if inspector is None or "revision" not in draft_columns:
        op.add_column(
            "digital_employee_drafts",
            sa.Column(
                "revision",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
    if (
        inspector is None
        or not inspector.has_table("digital_employee_draft_revisions")
    ):
        op.create_table(
            "digital_employee_draft_revisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("draft_id", sa.Uuid(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("change_note", sa.String(length=500), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["draft_id"],
                ["digital_employee_drafts.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "draft_id",
                "revision",
                name="uq_employee_draft_revision",
            ),
        )
    revision_indexes = (
        {
            index["name"]
            for index in inspector.get_indexes(
                "digital_employee_draft_revisions"
            )
        }
        if inspector is not None
        and inspector.has_table("digital_employee_draft_revisions")
        else set()
    )
    if (
        inspector is None
        or "ix_employee_draft_revisions_draft_time" not in revision_indexes
    ):
        op.create_index(
            "ix_employee_draft_revisions_draft_time",
            "digital_employee_draft_revisions",
            ["draft_id", "created_at"],
        )
    bind = op.get_bind()
    revisions = sa.table(
        "digital_employee_draft_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("draft_id", sa.Uuid()),
        sa.column("revision", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("snapshot_json", sa.JSON()),
        sa.column("change_note", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    drafts = sa.table(
        "digital_employee_drafts",
        sa.column("id", sa.Uuid()),
        sa.column("revision", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for draft in bind.execute(sa.select(drafts)).mappings():
        existing_revision = bind.execute(
            sa.select(revisions.c.id).where(
                revisions.c.draft_id == draft["id"],
                revisions.c.revision == draft["revision"],
            )
        ).scalar()
        if existing_revision is not None:
            continue
        bind.execute(
            revisions.insert().values(
                id=uuid4(),
                draft_id=draft["id"],
                revision=draft["revision"],
                status=draft["status"],
                snapshot_json={},
                change_note="Backfilled current draft state",
                created_by=draft["created_by"],
                created_at=draft["created_at"],
            )
        )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_draft_revisions_draft_time",
        table_name="digital_employee_draft_revisions",
    )
    op.drop_table("digital_employee_draft_revisions")
    op.drop_column("digital_employee_drafts", "revision")
