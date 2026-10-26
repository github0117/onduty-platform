from functools import lru_cache

from ticket_agent.model_gateway.local import LocalModelGateway
from ticket_agent.model_gateway.openai_compatible import OpenAICompatibleGateway
from ticket_agent.model_gateway.types import TicketModelGateway
from ticket_agent.shared.settings import get_settings


@lru_cache
def get_model_gateway() -> TicketModelGateway:
    settings = get_settings()
    if settings.model_provider == "openai_compatible":
        return OpenAICompatibleGateway(settings)
    return LocalModelGateway()

