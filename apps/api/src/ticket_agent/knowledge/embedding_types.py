from dataclasses import dataclass, field
from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingBatch:
    """Vectors plus the model that actually produced them.

    ``fallback_used`` is the only place a fallback may be observed: writers use
    ``model_name`` (not the configured name) so a fallback can never be stored
    as if it came from the remote model.
    """

    vectors: list[list[float]] = field(default_factory=list)
    model_name: str = ""
    fallback_used: bool = False


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
