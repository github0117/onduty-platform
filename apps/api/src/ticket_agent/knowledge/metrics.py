from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.tickets.models import AnswerDraft, Ticket


def embedding_quality(model_name: str) -> str:
    """Classify the effective embedding as demo-grade or semantic.

    The local provider is a deterministic feature hash: it is good enough for
    demos and regression tests, but it is not a semantic model.
    """
    return "demo" if model_name.startswith("local-hash") else "semantic"


class RagMetricsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        *,
        business_unit_id: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
        embedding_model: str = "",
        embedding_quality: str = "demo",
        reindex_pending_versions: int = 0,
        stale_evaluation_chunk_refs: int = 0,
    ) -> dict[str, object]:
        statement = select(AnswerDraft, Ticket).join(
            Ticket,
            Ticket.id == AnswerDraft.ticket_id,
        )
        if business_unit_id:
            statement = statement.where(Ticket.business_unit_id == business_unit_id)
        if from_at:
            statement = statement.where(AnswerDraft.created_at >= from_at)
        if to_at:
            statement = statement.where(AnswerDraft.created_at <= to_at)

        rows = self.session.execute(statement).all()
        providers: Counter[str] = Counter()
        citation_total = 0
        grounded_count = 0
        no_knowledge_count = 0
        claim_count = 0
        cited_claim_count = 0
        policy_claim_count = 0
        cited_policy_claim_count = 0
        semantic_verified_claim_count = 0
        semantic_unsupported_claim_count = 0
        for draft, _ticket in rows:
            citations = draft.citations_json or []
            claims = draft.claims_json or []
            citation_total += len(citations)
            claim_count += len(claims)
            for claim in claims:
                claim_citations = claim.get("cited_chunk_ids", [])
                if claim_citations:
                    cited_claim_count += 1
                if claim.get("claim_type") == "policy":
                    policy_claim_count += 1
                    if claim_citations:
                        cited_policy_claim_count += 1
                verdict = claim.get("verification_verdict")
                if verdict == "supported":
                    semantic_verified_claim_count += 1
                elif verdict == "unsupported":
                    semantic_unsupported_claim_count += 1
            if draft.grounding_status == "GROUNDED" or citations:
                grounded_count += 1
            else:
                no_knowledge_count += 1
            providers[draft.generator_provider or "unknown"] += 1

        count = len(rows)
        return {
            "draft_count": count,
            "grounded_count": grounded_count,
            "no_knowledge_count": no_knowledge_count,
            "citation_total": citation_total,
            "average_citations": citation_total / count if count else 0.0,
            "grounding_rate": grounded_count / count if count else 0.0,
            "claim_count": claim_count,
            "cited_claim_count": cited_claim_count,
            "policy_claim_count": policy_claim_count,
            "policy_citation_coverage": (
                cited_policy_claim_count / policy_claim_count
                if policy_claim_count
                else 0.0
            ),
            "semantic_verified_claim_count": semantic_verified_claim_count,
            "semantic_unsupported_claim_count": semantic_unsupported_claim_count,
            "provider_counts": dict(providers),
            "embedding_model": embedding_model,
            "embedding_quality": embedding_quality,
            "reindex_pending_versions": reindex_pending_versions,
            "stale_evaluation_chunk_refs": stale_evaluation_chunk_refs,
        }

