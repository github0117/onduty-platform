from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ticket_agent.agent_runs import models as agent_run_models  # noqa: F401
from ticket_agent.agent_skills import models as agent_skill_models  # noqa: F401
from ticket_agent.business_entries import (  # noqa: F401
    models as business_entry_models,
)
from ticket_agent.customer_service import (  # noqa: F401
    models as customer_service_models,
)
from ticket_agent.digital_employees import models as employee_models  # noqa: F401
from ticket_agent.ecommerce import models as ecommerce_models  # noqa: F401
from ticket_agent.knowledge import models as knowledge_models  # noqa: F401
from ticket_agent.mcp_connectors import models as mcp_models  # noqa: F401
from ticket_agent.model_gateway import models as model_models  # noqa: F401
from ticket_agent.shared.db import Base
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets import models  # noqa: F401
from ticket_agent.tools import models as tool_models  # noqa: F401
from ticket_agent.workforce import models as workforce_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
settings.ensure_sqlite_directory()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

