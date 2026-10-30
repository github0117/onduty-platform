from sqlalchemy.exc import OperationalError

from ticket_agent.shared.db import is_deadlock_error


class _PgError(Exception):
    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _wrapped(origin: BaseException) -> OperationalError:
    return OperationalError("INSERT INTO conversation_turn_events", {}, origin)


def test_sqlstate_40p01_is_a_deadlock() -> None:
    error = _wrapped(_PgError("deadlock detected", "40P01"))

    assert is_deadlock_error(error) is True


def test_psycopg_message_is_recognised_without_a_sqlstate() -> None:
    error = _wrapped(_PgError("deadlock detected\nDETAIL: ...", None))

    assert is_deadlock_error(error) is True


def test_pgcode_attribute_is_accepted() -> None:
    class _LegacyPgError(Exception):
        pgcode = "40P01"

    assert is_deadlock_error(_wrapped(_LegacyPgError("boom"))) is True


def test_other_database_errors_are_not_retried() -> None:
    error = _wrapped(_PgError("connection reset by peer", "08006"))

    assert is_deadlock_error(error) is False


def test_bare_exception_is_not_a_deadlock() -> None:
    assert is_deadlock_error(RuntimeError("deadlock detected")) is False
