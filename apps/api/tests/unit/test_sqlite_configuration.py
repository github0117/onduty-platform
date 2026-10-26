from sqlalchemy import text

from ticket_agent.shared.db import engine


def test_sqlite_uses_wal_and_busy_timeout() -> None:
    assert engine.dialect.name == "sqlite"

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 30000
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
