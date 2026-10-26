from functools import lru_cache
from typing import Protocol

import httpx

from ticket_agent.knowledge.retrieval import (
    HybridReranker,
    RankedCandidate,
    RetrievalCandidate,
)
from ticket_agent.model_gateway.usage import ModelUsageGuard, TokenUsage
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings, get_settings


class Reranker(Protocol):
    @property
    def name(self) -> str: ...

    def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> list[RankedCandidate]: ...


class ExternalHTTPReranker:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        usage_guard: ModelUsageGuard | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.rerank_timeout_seconds)
        self._fallback = HybridReranker(
            vector_weight=settings.knowledge_vector_weight,
            lexical_weight=settings.knowledge_lexical_weight,
            enabled=settings.knowledge_reranker == "hybrid",
        )
        self._usage_guard = usage_guard

    @property
    def name(self) -> str:
        return f"external:{self.settings.rerank_model_name}"

    def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> list[RankedCandidate]:
        started_monotonic = (
            self._usage_guard.start(purpose="rerank")
            if self._usage_guard
            else None
        )
        try:
            ranked, usage = self._remote_rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
            )
            if self._usage_guard and started_monotonic is not None:
                self._usage_guard.succeed(
                    purpose="rerank",
                    provider="openai_compatible",
                    model_name=self.settings.rerank_model_name,
                    usage=usage,
                    started_monotonic=started_monotonic,
                )
            return ranked
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            if self._usage_guard and started_monotonic is not None:
                self._usage_guard.fail(
                    purpose="rerank",
                    provider="openai_compatible",
                    model_name=self.settings.rerank_model_name,
                    started_monotonic=started_monotonic,
                    error_code=type(exc).__name__,
                )
            if not self.settings.rerank_fallback_to_local:
                raise RuntimeError("External reranker failed") from exc
            return self._fallback.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
            )

    def _remote_rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> tuple[list[RankedCandidate], TokenUsage]:
        if not self.settings.rerank_base_url or not self.settings.rerank_model_name:
            raise ValueError("Reranker URL and model name are required")

        redact = self.settings.model_data_redaction_enabled
        documents = [
            redact_sensitive_text(f"{item.title}\n{item.content}")
            if redact
            else f"{item.title}\n{item.content}"
            for item in candidates
        ]
        headers = {"Content-Type": "application/json"}
        if self.settings.rerank_api_key:
            headers["Authorization"] = f"Bearer {self.settings.rerank_api_key}"
        response = self._client.post(
            f"{self.settings.rerank_base_url.rstrip('/')}/rerank",
            headers=headers,
            json={
                "model": self.settings.rerank_model_name,
                "query": redact_sensitive_text(query) if redact else query,
                "documents": documents,
                "top_n": top_k,
            },
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError("Reranker returned no results")

        ranked: list[RankedCandidate] = []
        used_indexes: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise ValueError("Reranker result is invalid")
            index = int(item["index"])
            score = float(item["relevance_score"])
            if index < 0 or index >= len(candidates) or index in used_indexes:
                raise ValueError("Reranker returned an invalid index")
            if not 0.0 <= score <= 1.0:
                raise ValueError("Reranker score is outside [0, 1]")
            used_indexes.add(index)
            ranked.append(
                RankedCandidate(
                    candidate=candidates[index],
                    lexical_score=0.0,
                    final_score=score,
                )
            )
        ranked.sort(key=lambda item: item.final_score, reverse=True)
        usage_data = payload.get("usage")
        usage = TokenUsage()
        if isinstance(usage_data, dict):
            prompt_tokens = usage_data.get("prompt_tokens")
            completion_tokens = usage_data.get("completion_tokens")
            usage = TokenUsage(
                input_tokens=int(prompt_tokens) if isinstance(prompt_tokens, int) else 0,
                output_tokens=(
                    int(completion_tokens) if isinstance(completion_tokens, int) else 0
                ),
            )
        return ranked[:top_k], usage


@lru_cache
def get_reranker() -> Reranker:
    settings = get_settings()
    if settings.knowledge_rerank_provider == "external":
        return ExternalHTTPReranker(settings)
    return HybridReranker(
        vector_weight=settings.knowledge_vector_weight,
        lexical_weight=settings.knowledge_lexical_weight,
        enabled=settings.knowledge_reranker == "hybrid",
    )
