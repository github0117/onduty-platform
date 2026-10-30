"""external connectors, bindings and message ledger

Revision ID: a9d3c7e5b214
Revises: d4b9e1c7a2f3
Create Date: 2026-10-28 18:00:00.000000

One connector table serves inbound channels (email / signed webhook) and
read-only business systems. Message rows are the idempotency ledger: the
unique (connector_id, external_message_id) pair is what stops duplicate
delivery from opening a second conversation. Existing conversations keep
NULL external columns, so the migration is additive.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d3c7e5b214"
down_revision: str | None = "d4b9e1c7a2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_connectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("connector_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("connector_type", sa.String(length=24), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("field_mapping_json", sa.JSON(), nullable=False),
        sa.Column("secret_ref", sa.String(length=200), nullable=True),
        sa.Column("auto_reply_enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_health_status", sa.String(length=24), nullable=True),
        sa.Column(
            "last_health_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_health_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "business_unit_id",
            "connector_key",
            name="uq_external_connector_business_key",
        ),
    )
    op.create_index(
        "ix_external_connectors_unit_status",
        "external_connectors",
        ["business_unit_id", "status"],
    )

    op.create_table(
        "external_connector_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("service_entry_id", sa.Uuid(), nullable=True),
        sa.Column("employee_id", sa.Uuid(), nullable=True),
        sa.Column("allowed_operations_json", sa.JSON(), nullable=False),
        sa.Column("write_approved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["external_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["digital_employees.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["service_entry_id"],
            ["business_service_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connector_id",
            "service_entry_id",
            name="uq_external_connector_entry",
        ),
    )
    op.create_index(
        "ix_external_connector_bindings_connector",
        "external_connector_bindings",
        ["connector_id"],
    )

    op.create_table(
        "external_inbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column(
            "external_message_id",
            sa.String(length=256),
            nullable=False,
        ),
        sa.Column(
            "external_conversation_id",
            sa.String(length=256),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("ticket_id", sa.Uuid(), nullable=True),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["external_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["conversation_turns.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connector_id",
            "external_message_id",
            name="uq_external_inbound_message",
        ),
    )
    op.create_index(
        "ix_external_inbound_connector_created",
        "external_inbound_messages",
        ["connector_id", "created_at"],
    )

    op.create_table(
        "external_outbound_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=False),
        sa.Column("business_unit_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("outbox_event_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("external_message_id", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connector_id"],
            ["external_connectors.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["customer_conversations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connector_id",
            "idempotency_key",
            name="uq_external_outbound_idempotency",
        ),
    )
    op.create_index(
        "ix_external_outbound_connector_created",
        "external_outbound_messages",
        ["connector_id", "created_at"],
    )

    with op.batch_alter_table("customer_conversations") as batch:
        batch.add_column(
            sa.Column("external_connector_id", sa.Uuid(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "external_thread_id",
                sa.String(length=256),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "external_subject",
                sa.String(length=500),
                nullable=True,
            )
        )
        batch.create_foreign_key(
            "fk_customer_conversations_external_connector",
            "external_connectors",
            ["external_connector_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint(
            "uq_customer_conversations_external_thread",
            ["external_connector_id", "external_thread_id"],
        )
        batch.create_index(
            "ix_customer_conversations_external_connector_id",
            ["external_connector_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("customer_conversations") as batch:
        batch.drop_index(
            "ix_customer_conversations_external_connector_id"
        )
        batch.drop_constraint(
            "uq_customer_conversations_external_thread",
            type_="unique",
        )
        batch.drop_constraint(
            "fk_customer_conversations_external_connector",
            type_="foreignkey",
        )
        batch.drop_column("external_subject")
        batch.drop_column("external_thread_id")
        batch.drop_column("external_connector_id")

    op.drop_index(
        "ix_external_outbound_connector_created",
        table_name="external_outbound_messages",
    )
    op.drop_table("external_outbound_messages")
    op.drop_index(
        "ix_external_inbound_connector_created",
        table_name="external_inbound_messages",
    )
    op.drop_table("external_inbound_messages")
    op.drop_index(
        "ix_external_connector_bindings_connector",
        table_name="external_connector_bindings",
    )
    op.drop_table("external_connector_bindings")
    op.drop_index(
        "ix_external_connectors_unit_status",
        table_name="external_connectors",
    )
    op.drop_table("external_connectors")
