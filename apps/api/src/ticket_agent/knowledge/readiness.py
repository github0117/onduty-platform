from ticket_agent.knowledge.embedding_factory import remote_embedding_ready
from ticket_agent.shared.settings import Settings


def rag_readiness_issues(settings: Settings) -> list[str]:
    """Blocking RAG configuration gaps outside development/test.

    These settings do not break the application at import time, but they turn
    retrieval into a demo that silently returns low-quality answers. Readiness
    is the right place to stop that.
    """
    if settings.is_development:
        return []

    issues: list[str] = []
    if settings.embedding_provider != "openai_compatible" or not (
        remote_embedding_ready(settings)
    ):
        issues.append(
            "embedding: EMBEDDING_PROVIDER must be openai_compatible with "
            "EMBEDDING_BASE_URL, EMBEDDING_API_KEY and EMBEDDING_MODEL_NAME; "
            "local-hash demo vectors are not allowed in production"
        )
    if settings.knowledge_retrieval_mode != "hybrid":
        issues.append(
            "retrieval: KNOWLEDGE_RETRIEVAL_MODE must be hybrid in production"
        )
    if not _remote_reranker_ready(settings):
        issues.append(
            "rerank: KNOWLEDGE_RERANK_PROVIDER must be external or dashscope "
            "with its endpoint and model configured"
        )
    return issues


def _remote_reranker_ready(settings: Settings) -> bool:
    provider = settings.knowledge_rerank_provider
    if provider == "dashscope":
        return bool(settings.rerank_model_name) and bool(
            settings.rerank_api_key or settings.model_api_key
        )
    if provider == "external":
        return bool(settings.rerank_base_url) and bool(settings.rerank_model_name)
    return False
