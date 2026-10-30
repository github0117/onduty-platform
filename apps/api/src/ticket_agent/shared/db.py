import logging
from collections.abc import Callable, Generator
from time import sleep
from typing import Any, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ticket_agent.shared.settings import get_settings

logger = logging.getLogger(__name__)

Result = TypeVar("Result")

# Both sides of a conversation/turn lock cycle are retried a few times: the
# deadlock only lasts as long as the other side's transaction, and the delay
# spaces out the attempts.
DEADLOCK_RETRY_ATTEMPTS = 3
DEADLOCK_RETRY_BACKOFF_SECONDS = 0.05


class Base(DeclarativeBase):
    pass


settings = get_settings()
settings.ensure_sqlite_directory()

is_sqlite = settings.database_url.startswith("sqlite")
connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if is_sqlite
    else {}
)
engine_options: dict[str, object] = {
    "pool_pre_ping": True,
    "connect_args": connect_args,
}
if not settings.database_url.startswith("sqlite"):
    engine_options.update(
        {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout_seconds,
        }
    )
engine = create_engine(settings.database_url, **engine_options)

if is_sqlite:

    @event.listens_for(engine, "connect")
    def _configure_sqlite(
        dbapi_connection: Any,
        _connection_record: Any,
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def is_deadlock_error(exc: BaseException) -> bool:
    """True when PostgreSQL aborted this transaction to break a deadlock.

    Two writers can take each other's row locks (a takeover cancels turns while
    a worker finishes one), and PostgreSQL kills one transaction with SQLSTATE
    ``40P01``. The loser's work is rolled back whole, so the caller may retry
    the operation from a fresh transaction.
    """
    if not isinstance(exc, OperationalError):
        return False
    origin = getattr(exc, "orig", exc)
    sqlstate = getattr(origin, "sqlstate", None) or getattr(origin, "pgcode", None)
    if sqlstate == "40P01":
        return True
    return "deadlock detected" in str(origin).lower()


def run_with_deadlock_retry(
    session: Session,
    label: str,
    operation: Callable[[], Result],
) -> Result:
    """Run ``operation``, retrying when PostgreSQL aborts it as the deadlock victim.

    A rolled-back transaction has written nothing, so re-running it in a fresh
    transaction is safe; every operation passed here re-reads the state it
    validates against (version checks, idempotency keys, the current employee),
    so a retry cannot apply a decision made against a stale snapshot.
    """
    for attempt in range(DEADLOCK_RETRY_ATTEMPTS):
        try:
            return operation()
        except OperationalError as exc:
            session.rollback()
            if (
                not is_deadlock_error(exc)
                or attempt + 1 >= DEADLOCK_RETRY_ATTEMPTS
            ):
                raise
            logger.warning(
                "%s lost a deadlock with a live turn; retrying (attempt %s/%s)",
                label,
                attempt + 2,
                DEADLOCK_RETRY_ATTEMPTS,
            )
            sleep(DEADLOCK_RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise AssertionError("unreachable")


def init_db() -> None:
    from ticket_agent.business_entries import models as business_entry_models  # noqa: F401
    from ticket_agent.connectors import models as connector_models  # noqa: F401
    from ticket_agent.customer_service import models as customer_service_models  # noqa: F401
    from ticket_agent.digital_employees import models as employee_models  # noqa: F401
    from ticket_agent.knowledge import models as knowledge_models  # noqa: F401
    from ticket_agent.model_gateway import models as model_models  # noqa: F401
    from ticket_agent.tickets import models  # noqa: F401
    from ticket_agent.tools import models as tool_models  # noqa: F401

    Base.metadata.create_all(bind=engine)

