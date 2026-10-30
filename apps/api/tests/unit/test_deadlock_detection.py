from typing import cast

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ticket_agent.shared.db import (
    DEADLOCK_RETRY_ATTEMPTS,
    is_deadlock_error,
    run_with_deadlock_retry,
)


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


class _RolledBackSession:
    def __init__(self) -> None:
        self.rollbacks = 0

    def rollback(self) -> None:
        self.rollbacks += 1


def test_operation_is_retried_once_after_a_deadlock() -> None:
    session = _RolledBackSession()
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise _wrapped(_PgError("deadlock detected", "40P01"))
        return "done"

    assert (
        run_with_deadlock_retry(cast(Session, session), "test", operation)
        == "done"
    )
    assert len(calls) == 2
    assert session.rollbacks == 1


def test_other_errors_are_not_retried() -> None:
    session = _RolledBackSession()
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        raise _wrapped(_PgError("connection reset by peer", "08006"))

    with pytest.raises(OperationalError):
        run_with_deadlock_retry(cast(Session, session), "test", operation)
    assert len(calls) == 1


def test_a_persistent_deadlock_stops_after_the_attempt_budget() -> None:
    session = _RolledBackSession()
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        raise _wrapped(_PgError("deadlock detected", "40P01"))

    with pytest.raises(OperationalError):
        run_with_deadlock_retry(cast(Session, session), "test", operation)
    assert len(calls) == DEADLOCK_RETRY_ATTEMPTS
    assert session.rollbacks == DEADLOCK_RETRY_ATTEMPTS
