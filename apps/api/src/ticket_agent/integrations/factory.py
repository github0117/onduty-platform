from functools import lru_cache

from ticket_agent.integrations.http_json import HTTPJSONTicketAdapter
from ticket_agent.integrations.local import LocalTicketAdapter
from ticket_agent.integrations.types import TicketAdapter
from ticket_agent.shared.settings import get_settings


@lru_cache
def get_ticket_adapter() -> TicketAdapter:
    settings = get_settings()
    if settings.ticket_integration_provider == "http_json":
        return HTTPJSONTicketAdapter(settings)
    return LocalTicketAdapter()

