#!/usr/bin/env python3
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from ticket_agent.shared.db import engine

INITIAL_REVISION = "3abfe428b4e3"
OUTBOX_REVISION = "35d8db2411d5"
KNOWLEDGE_REVISION = "fbd383c8b02f"
SOURCE_REVISION = "d08d2f653bcc"
ASYNC_INGESTION_REVISION = "488b7946b525"
CLAIM_REVISION = "0b3a7f092c3c"
SYNC_REVISION = "e3cb7232b71c"
CURRENT_REVISION = "d2f7a4c93e61"


def main() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar()
        if current_revision:
            return
    application_tables = tables - {"alembic_version"}
    if not application_tables:
        return

    revision = _detect_revision(application_tables, inspector)
    config = Config("alembic.ini")
    command.stamp(config, revision)
    print(f"Stamped existing development database at {revision}.")


def _detect_revision(tables: set[str], inspector: object) -> str:
    if "digital_employees" in tables:
        return CURRENT_REVISION
    if "tickets" in tables:
        ticket_columns = {
            column["name"]
            for column in inspector.get_columns("tickets")  # type: ignore[attr-defined]
        }
        if "sync_status" in ticket_columns:
            return SYNC_REVISION
    if "answer_drafts" in tables:
        draft_columns = {
            column["name"]
            for column in inspector.get_columns("answer_drafts")  # type: ignore[attr-defined]
        }
        if "claims_json" in draft_columns:
            return CLAIM_REVISION
    if "knowledge_versions" in tables:
        columns = {
            column["name"]
            for column in inspector.get_columns("knowledge_versions")  # type: ignore[attr-defined]
        }
        if "source_object_key" in columns:
            return ASYNC_INGESTION_REVISION
        if "source_filename" in columns:
            return SOURCE_REVISION
        return KNOWLEDGE_REVISION
    if "outbox_events" in tables:
        columns = {
            column["name"]
            for column in inspector.get_columns("outbox_events")  # type: ignore[attr-defined]
        }
        if "last_attempt_at" in columns:
            return OUTBOX_REVISION
    if {
        "tickets",
        "audit_events",
        "ticket_analyses",
        "answer_drafts",
        "workflow_transitions",
        "outbox_events",
    }.issubset(tables):
        return INITIAL_REVISION
    raise RuntimeError(
        "Existing database does not match a known application schema; refusing to stamp it."
    )


if __name__ == "__main__":
    main()

