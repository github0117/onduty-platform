"""skill runtime contract and per-turn completion snapshot

Revision ID: d9b2e5f7a1c4
Revises: c4f1a7d29b63
Create Date: 2026-10-29 18:20:00.000000

A Skill used to be a prompt fragment: nothing could tell whether the steps it
described had actually been executed. ``definition_json`` turns that text into
a machine-checkable contract, and every turn now records which contract it
ran and whether the required steps were satisfied.

* ``agent_skills.definition_json`` (nullable) / ``definition_version``: the
  structured contract and its own version. NULL keeps old skills in loose
  mode — they still guide the model, but no step is asserted.
* ``conversation_turns.skill_code / skill_version / skill_snapshot_json``:
  the contract as it existed for this turn. Later edits cannot rewrite what a
  finished turn is judged against.
* ``conversation_turns.completion_json``: per-step and per-criterion result.

All columns are additive. Old rows read as "no contract recorded".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9b2e5f7a1c4"
down_revision: str | None = "c4f1a7d29b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_skills",
        sa.Column("definition_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "agent_skills",
        sa.Column(
            "definition_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("skill_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("skill_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("skill_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("completion_json", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_conversation_turns_skill_code",
        "conversation_turns",
        ["skill_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_turns_skill_code",
        table_name="conversation_turns",
    )
    op.drop_column("conversation_turns", "completion_json")
    op.drop_column("conversation_turns", "skill_snapshot_json")
    op.drop_column("conversation_turns", "skill_version")
    op.drop_column("conversation_turns", "skill_code")
    op.drop_column("agent_skills", "definition_version")
    op.drop_column("agent_skills", "definition_json")
