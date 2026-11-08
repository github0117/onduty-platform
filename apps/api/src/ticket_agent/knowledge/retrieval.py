from dataclasses import dataclass
from uuid import UUID

from ticket_agent.knowledge.local_embedding import tokenize_text


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: UUID
    document_id: UUID
    title: str
    version: str
    content: str
    vector_score: float
    space_id: UUID | None = None


@dataclass(frozen=True)
class RankedCandidate:
    candidate: RetrievalCandidate
    lexical_score: float
    final_score: float


class HybridReranker:
    def __init__(
        self,
        *,
        vector_weight: float = 0.6,
        lexical_weight: float = 0.4,
        enabled: bool = True,
    ) -> None:
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight
        self.enabled = enabled

    @property
    def name(self) -> str:
        return "hybrid" if self.enabled else "vector"

    def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
        top_k: int,
    ) -> list[RankedCandidate]:
        ranked: list[RankedCandidate] = []
        for candidate in candidates:
            lexical_score = (
                _lexical_score(query, f"{candidate.title}\n{candidate.content}")
                if self.enabled
                else 0.0
            )
            vector_score = max(0.0, min(1.0, candidate.vector_score))
            if self.enabled:
                final_score = (
                    self.vector_weight * vector_score
                    + self.lexical_weight * lexical_score
                )
            else:
                final_score = vector_score
            ranked.append(
                RankedCandidate(
                    candidate=candidate,
                    lexical_score=lexical_score,
                    final_score=final_score,
                )
            )
        ranked.sort(
            key=lambda item: (
                item.final_score,
                item.candidate.vector_score,
            ),
            reverse=True,
        )
        return ranked[:top_k]


def _lexical_score(query: str, content: str) -> float:
    query_tokens = set(tokenize_text(query))
    if not query_tokens:
        return 0.0
    content_tokens = set(tokenize_text(content))
    overlap = len(query_tokens & content_tokens) / len(query_tokens)
    normalized_query = " ".join(query.lower().split())
    normalized_content = " ".join(content.lower().split())
    phrase_bonus = 0.1 if normalized_query and normalized_query in normalized_content else 0.0
    return min(1.0, overlap + phrase_bonus)

