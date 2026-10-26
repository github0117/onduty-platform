from functools import lru_cache

from ticket_agent.knowledge.embedding_types import EmbeddingProvider
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.settings import get_settings


@lru_cache
def _get_default_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(settings)
    return LocalEmbeddingProvider(settings.embedding_dimensions)


def get_embedding_provider(
    usage_guard: ModelUsageGuard | None = None,
) -> EmbeddingProvider:
    if usage_guard is None:
        return _get_default_embedding_provider()
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(
            settings,
            usage_guard=usage_guard,
        )
    return LocalEmbeddingProvider(settings.embedding_dimensions)

