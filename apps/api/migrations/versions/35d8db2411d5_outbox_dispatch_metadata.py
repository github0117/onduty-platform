"""outbox dispatch metadata

Revision ID: 35d8db2411d5
Revises: 3abfe428b4e3
Create Date: 2026-10-23 09:23:17.577190
"""

from collections.abc import Sequence

from alembic import context, op
import sqlalchemy as sa


revision: str = '35d8db2411d5'
down_revision: str | None = '3abfe428b4e3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    bind = op.get_bind()
    if context.is_offline_mode():
        op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))
        op.add_column(
            "outbox_events",
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "outbox_events",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )
        return
    inspector = sa.inspect(bind)
    columns = {
        column["name"]: column
        for column in inspector.get_columns("outbox_events")
    }
    if "last_error" not in columns:
        op.add_column("outbox_events", sa.Column("last_error", sa.Text(), nullable=True))
    if "last_attempt_at" not in columns:
        op.add_column(
            "outbox_events",
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        )

    updated_at = columns.get("updated_at")
    if updated_at is None:
        if bind.dialect.name == "sqlite":
            op.add_column(
                "outbox_events",
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.execute(
                "UPDATE outbox_events SET updated_at = created_at "
                "WHERE updated_at IS NULL"
            )
            with op.batch_alter_table("outbox_events") as batch:
                batch.alter_column(
                    "updated_at",
                    existing_type=sa.DateTime(timezone=True),
                    nullable=False,
                )
        else:
            op.add_column(
                "outbox_events",
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                    nullable=False,
                ),
            )
    elif bind.dialect.name == "sqlite" and updated_at.get("nullable", False):
        op.execute(
            "UPDATE outbox_events SET updated_at = created_at "
            "WHERE updated_at IS NULL"
        )
        with op.batch_alter_table("outbox_events") as batch:
            batch.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )


def downgrade() -> None:
    """Revert the migration."""
    if context.is_offline_mode():
        op.drop_column("outbox_events", "updated_at")
        op.drop_column("outbox_events", "last_attempt_at")
        op.drop_column("outbox_events", "last_error")
        return
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("outbox_events")
    }
    for column in ("updated_at", "last_attempt_at", "last_error"):
        if column in columns:
            op.drop_column("outbox_events", column)

