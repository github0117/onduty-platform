"""Fail fast when a deployment's database and migration scripts disagree.

``alembic upgrade head`` reports the two dangerous states badly. If the
database is on a revision this image does not ship (a rollback during deploy,
or a newer image touching an older database), the upgrade dies on a missing
revision far from the cause; if the repository ships diverged heads, alembic
picks one of them silently. Both are checked here before anything is applied,
and the same script is run again after the upgrade to confirm the database
landed exactly on head.

The database URL comes from the application settings and is never printed: it
carries the password.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from ticket_agent.shared.settings import get_settings

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_PENDING = 3
EXIT_UNAVAILABLE = 4

AT_HEAD = "at_head"
PENDING = "pending"
EMPTY = "empty"
UNKNOWN = "unknown"
MULTIPLE_HEADS = "multiple_heads"

VERSION_TABLE = "alembic_version"


@dataclass(frozen=True)
class MigrationState:
    status: str
    current: str | None
    heads: tuple[str, ...]


def inspect_migration_state(
    current: str | None,
    heads: tuple[str, ...],
    known_revisions: tuple[str, ...],
) -> MigrationState:
    """Classify the database revision against the revisions this image ships."""
    if len(heads) != 1:
        status = MULTIPLE_HEADS
    elif current is None:
        status = EMPTY
    elif current in heads:
        status = AT_HEAD
    elif current in known_revisions:
        status = PENDING
    else:
        status = UNKNOWN
    return MigrationState(status=status, current=current, heads=tuple(heads))


def script_revisions(config: Config) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the repository's heads and every reachable revision."""
    script = ScriptDirectory.from_config(config)
    heads = tuple(script.get_heads())
    known = tuple(
        revision.revision for revision in script.walk_revisions()
    )
    return heads, known


def database_current_revision(database_url: str) -> str | None:
    """Return the revision recorded in the database, or None on a fresh schema."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table(VERSION_TABLE):
                return None
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _describe(state: MigrationState) -> str:
    current = state.current or "-"
    heads = ",".join(state.heads) or "-"
    return (
        f"migration_preflight={state.status} "
        f"current={current} head={heads}"
    )


def _guidance(state: MigrationState) -> str:
    if state.status == MULTIPLE_HEADS:
        return (
            f"expected exactly one migration head, found {len(state.heads)}: "
            f"{', '.join(state.heads) or 'none'}. Resolve the branch before deploying."
        )
    if state.status == UNKNOWN:
        return (
            f"database is on revision {state.current}, which this image does not "
            "ship. Deploy the image that created it, or restore a backup taken "
            "at a revision this image knows."
        )
    current = (
        f"revision {state.current}"
        if state.current is not None
        else "no revision (fresh schema)"
    )
    return (
        f"database is on {current} but head is {', '.join(state.heads)}. "
        "Run 'alembic upgrade head' first."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check that the database revision is reachable from the migrations "
            "shipped in this image."
        ),
    )
    parser.add_argument(
        "--allow-pending",
        action="store_true",
        help="exit 0 when the database is behind head (run before the upgrade)",
    )
    parser.add_argument(
        "--expect-head",
        action="store_true",
        help="require the database to be exactly at head (run after the upgrade)",
    )
    parser.add_argument(
        "--config",
        default="alembic.ini",
        help="alembic configuration file (default: alembic.ini)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="override the database URL from the application settings",
    )
    args = parser.parse_args(argv)

    try:
        heads, known = script_revisions(Config(args.config))
    except Exception as error:  # noqa: BLE001 - reported, not swallowed
        print(
            f"migration_preflight=config_error error={type(error).__name__}",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    database_url = args.database_url or get_settings().database_url
    try:
        current = database_current_revision(database_url)
    except Exception as error:  # noqa: BLE001 - reported, not swallowed
        print(
            f"migration_preflight=database_unavailable "
            f"error={type(error).__name__}",
            file=sys.stderr,
        )
        return EXIT_UNAVAILABLE

    state = inspect_migration_state(current, heads, known)
    print(_describe(state), flush=True)

    if state.status in {MULTIPLE_HEADS, UNKNOWN}:
        print(_guidance(state), file=sys.stderr)
        return EXIT_CONFIG
    if state.status == PENDING and not args.allow_pending:
        print(_guidance(state), file=sys.stderr)
        return EXIT_PENDING
    if args.expect_head and state.status != AT_HEAD:
        print(_guidance(state), file=sys.stderr)
        return EXIT_PENDING
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
