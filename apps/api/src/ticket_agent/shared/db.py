from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ticket_agent.shared.settings import get_settings


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


def init_db() -> None:
    from ticket_agent.business_entries import models as business_entry_models  # noqa: F401
    from ticket_agent.customer_service import models as customer_service_models  # noqa: F401
    from ticket_agent.digital_employees import models as employee_models  # noqa: F401
    from ticket_agent.knowledge import models as knowledge_models  # noqa: F401
    from ticket_agent.model_gateway import models as model_models  # noqa: F401
    from ticket_agent.tickets import models  # noqa: F401
    from ticket_agent.tools import models as tool_models  # noqa: F401

    Base.metadata.create_all(bind=engine)

