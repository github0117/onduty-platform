import logging
from functools import lru_cache

from ticket_agent.knowledge.embedding_types import EmbeddingProvider
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _remote_embedding_ready(settings: Settings) -> bool:
    """Whether a remote embedding endpoint is actually configured.

    A deployment that asks for ``openai_compatible`` without a key is almost
    always a demo checkout of ``.env.example``: falling back to the local
    feature hash immediately is much better than failing every request once.
    Self-hosted endpoints without a credential must set
    ``EMBEDDING_ALLOW_EMPTY_API_KEY=true`` to opt out of this guard.
    """
    if not settings.embedding_base_url:
        return False
    return bool(settings.embedding_api_key) or settings.embedding_allow_empty_api_key


@lru_cache
def _get_default_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible":
        if _remote_embedding_ready(settings):
            return OpenAICompatibleEmbeddingProvider(settings)
        logger.warning(
            "Embedding provider is openai_compatible but no endpoint/key is "
            "configured; using the local feature-hash embedding (demo mode). "
            "Set EMBEDDING_BASE_URL and EMBEDDING_API_KEY for semantic search."
        )
    return LocalEmbeddingProvider(settings.embedding_dimensions)


def get_embedding_provider(
    usage_guard: ModelUsageGuard | None = None,
) -> EmbeddingProvider:
    if usage_guard is None:
        return _get_default_embedding_provider()
    settings = get_settings()
    if settings.embedding_provider == "openai_compatible" and _remote_embedding_ready(
        settings
    ):
        return OpenAICompatibleEmbeddingProvider(
            settings,
            usage_guard=usage_guard,
        )
    return LocalEmbeddingProvider(settings.embedding_dimensions)
