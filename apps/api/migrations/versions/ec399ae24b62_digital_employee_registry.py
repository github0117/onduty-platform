"""digital employee registry

Revision ID: ec399ae24b62
Revises: e3cb7232b71c
Create Date: 2026-10-23 12:21:50.647647
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'ec399ae24b62'
down_revision: str | None = 'e3cb7232b71c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    bind = op.get_bind()
    op.create_table('digital_employees',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('employee_key', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('scenario_type', sa.String(length=64), nullable=False),
    sa.Column('workflow_key', sa.String(length=100), nullable=False),
    sa.Column('business_unit_id', sa.String(length=64), nullable=False),
    sa.Column('service_identity', sa.String(length=160), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('handoff_queue', sa.String(length=64), nullable=False),
    sa.Column('knowledge_policy_json', sa.JSON(), nullable=False),
    sa.Column('model_profile_json', sa.JSON(), nullable=False),
    sa.Column('tool_allowlist_json', sa.JSON(), nullable=False),
    sa.Column('created_by', sa.String(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_unit_id', 'employee_key', name='uq_digital_employee_business_key')
    )
    op.create_index('ix_digital_employees_unit_status', 'digital_employees', ['business_unit_id', 'status'], unique=False)
    op.execute(
        sa.text(
            """
            INSERT INTO digital_employees (
                id, employee_key, name, version, scenario_type, workflow_key,
                business_unit_id, service_identity, status, handoff_queue,
                knowledge_policy_json, model_profile_json, tool_allowlist_json,
                created_by, created_at, updated_at
            ) VALUES (
                '00000000-0000-0000-0000-000000000101',
                'customer_service_ticket_v1',
                '客服工单数字员工',
                '1.0.0',
                'customer_service_ticket',
                'customer_service_ticket_v1',
                'bu_demo',
                'digital_agent.ticket.v1',
                'ACTIVE',
                'MANUAL_TRIAGE',
                '{"default_scope":{"audience":"support_agent"}}',
                '{}',
                '["ticket.read","ticket.sync"]',
                'system',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            """
        )
    )
    op.add_column('tickets', sa.Column('employee_id', sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE tickets
            SET employee_id = '00000000-0000-0000-0000-000000000101'
            WHERE employee_id IS NULL
            """
        )
    )
    op.create_index(op.f('ix_tickets_employee_id'), 'tickets', ['employee_id'], unique=False)
    if bind.dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_tickets_employee_id",
            'tickets',
            'digital_employees',
            ['employee_id'],
            ['id'],
            ondelete='RESTRICT',
        )


def downgrade() -> None:
    """Revert the migration."""
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint('fk_tickets_employee_id', 'tickets', type_='foreignkey')
    op.drop_index(op.f('ix_tickets_employee_id'), table_name='tickets')
    op.drop_column('tickets', 'employee_id')
    op.drop_index('ix_digital_employees_unit_status', table_name='digital_employees')
    op.drop_table('digital_employees')

