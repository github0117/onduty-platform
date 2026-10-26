from math import isfinite

import httpx

from ticket_agent.knowledge.embedding_types import EmbeddingProviderError
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.model_gateway.types import ModelGatewayError
from ticket_agent.model_gateway.usage import ModelUsageGuard, TokenUsage
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import Settings


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        usage_guard: ModelUsageGuard | None = None,
    ) -> None:
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.embedding_timeout_seconds)
        self._local = LocalEmbeddingProvider(settings.embedding_dimensions)
        self._usage_guard = usage_guard

    @property
    def name(self) -> str:
        return f"openai-compatible:{self.settings.embedding_model_name}"

    @property
    def dimensions(self) -> int:
        return self.settings.embedding_dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        try:
            started_monotonic = (
                self._usage_guard.start(purpose="embedding")
                if self._usage_guard
                else None
            )
        except ModelGatewayError:
            if self.settings.embedding_fallback_to_local:
                return self._local.embed_texts(texts)
            raise
        try:
            embeddings, usage = self._embed_remote(texts)
            if self._usage_guard and started_monotonic is not None:
                self._usage_guard.succeed(
                    purpose="embedding",
                    provider="openai_compatible",
                    model_name=self.settings.embedding_model_name,
                    usage=usage,
                    started_monotonic=started_monotonic,
                )
            return embeddings
        except (httpx.HTTPError, EmbeddingProviderError, ValueError) as exc:
            if self._usage_guard and started_monotonic is not None:
                self._usage_guard.fail(
                    purpose="embedding",
                    provider="openai_compatible",
                    model_name=self.settings.embedding_model_name,
                    started_monotonic=started_monotonic,
                    error_code=type(exc).__name__,
                )
            if not self.settings.embedding_fallback_to_local:
                raise EmbeddingProviderError(str(exc)) from exc
            return self._local.embed_texts(texts)

    def _embed_remote(
        self,
        texts: list[str],
    ) -> tuple[list[list[float]], TokenUsage]:
        base_url = self.settings.embedding_base_url or self.settings.model_base_url
        if not base_url or not self.settings.embedding_model_name:
            raise EmbeddingProviderError("Embedding base URL and model name are required")

        redacted = (
            [redact_sensitive_text(text) for text in texts]
            if self.settings.model_data_redaction_enabled
            else texts
        )
        headers = {"Content-Type": "application/json"}
        api_key = self.settings.embedding_api_key or self.settings.model_api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = self._client.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers=headers,
            json={"model": self.settings.embedding_model_name, "input": redacted},
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingProviderError("Embedding response count does not match input")

        embeddings: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingProviderError("Embedding response item is invalid")
            embedding = item.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != self.dimensions:
                raise EmbeddingProviderError("Embedding dimension is invalid")
            values = [float(value) for value in embedding]
            if not all(isfinite(value) for value in values):
                raise EmbeddingProviderError("Embedding contains non-finite values")
            embeddings.append(values)
        usage_data = payload.get("usage")
        usage = TokenUsage()
        if isinstance(usage_data, dict):
            total_tokens = usage_data.get("total_tokens")
            prompt_tokens = usage_data.get("prompt_tokens")
            tokens = (
                total_tokens
                if isinstance(total_tokens, int)
                else prompt_tokens
                if isinstance(prompt_tokens, int)
                else 0
            )
            usage = TokenUsage(input_tokens=tokens)
        return embeddings, usage

