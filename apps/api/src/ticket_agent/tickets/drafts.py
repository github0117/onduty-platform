from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.knowledge.claim_verifier import (
    ClaimToVerify,
    ClaimVerifier,
    get_claim_verifier,
)
from ticket_agent.knowledge.service import KnowledgeHit
from ticket_agent.model_gateway.factory import get_model_gateway
from ticket_agent.model_gateway.types import DraftSnippet, TicketModelGateway
from ticket_agent.routing.policy import RoutingDecision


@dataclass(frozen=True)
class DraftResult:
    text: str
    citations: list[dict[str, str | None]]
    claims: list[dict[str, object]]
    provider: str
    model: str
    fallback_used: bool
    grounding_status: str


@dataclass(frozen=True)
class DraftEvidence:
    chunk_id: str
    title: str
    version: str
    content: str
    citation: dict[str, Any]


class DraftService:
    """Generate a grounded response through the configured model gateway."""

    def __init__(
        self,
        gateway: TicketModelGateway | None = None,
        claim_verifier: ClaimVerifier | None = None,
        use_configured_claim_verifier: bool = True,
    ) -> None:
        self.gateway = gateway or get_model_gateway()
        if claim_verifier is not None:
            self._claim_verifier: ClaimVerifier | None = claim_verifier
        elif use_configured_claim_verifier:
            self._claim_verifier = get_claim_verifier()
        else:
            self._claim_verifier = None

    def generate(
        self,
        *,
        subject: str,
        body: str,
        analysis: AnalysisResult,
        routing: RoutingDecision,
        knowledge_hits: list[KnowledgeHit] | None = None,
        skill_instructions: str | None = None,
        external_evidence: list[DraftEvidence] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> DraftResult:
        hits = knowledge_hits or []
        evidence = external_evidence or []
        snippets = [
            DraftSnippet(
                chunk_id=str(hit.chunk_id),
                title=hit.title,
                version=hit.version,
                content=hit.content,
            )
            for hit in hits[:5]
        ]
        snippets.extend(
            DraftSnippet(
                chunk_id=item.chunk_id,
                title=item.title,
                version=item.version,
                content=item.content,
            )
            for item in evidence[:3]
        )
        response = self.gateway.generate_draft(
            subject=subject,
            body=body,
            category=analysis.category_primary,
            queue_id=routing.queue_id,
            snippets=snippets[:8],
            skill_instructions=skill_instructions,
            on_text_delta=on_text_delta,
        )
        citations_by_id = {
            str(hit.chunk_id): {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "space_id": str(hit.space_id) if hit.space_id else None,
                "title": hit.title,
                "version": hit.version,
            }
            for hit in hits
        }
        citations_by_id.update(
            {
                item.chunk_id: item.citation
                for item in evidence
            }
        )
        citations = [
            citations_by_id[chunk_id]
            for chunk_id in response.draft.cited_chunk_ids
            if chunk_id in citations_by_id
        ]
        verification_by_index = {
            verification.claim_index: verification
            for verification in response.claim_verifications
        }
        snippet_content_by_id = {
            snippet.chunk_id: snippet.content for snippet in snippets
        }
        pending_verifications: list[ClaimToVerify] = []
        for index, claim in enumerate(response.draft.claims):
            if index in verification_by_index:
                continue
            sources = [
                snippet_content_by_id[chunk_id]
                for chunk_id in claim.cited_chunk_ids
                if chunk_id in snippet_content_by_id
            ]
            if sources:
                pending_verifications.append(
                    ClaimToVerify(
                        claim_index=index,
                        text=claim.text,
                        claim_type=claim.claim_type,
                        sources=sources,
                    )
                )
        if pending_verifications and self._claim_verifier is not None:
            for verified in self._claim_verifier.verify(
                pending_verifications
            ):
                verification_by_index[verified.claim_index] = verified
        claims: list[dict[str, object]] = []
        for index, claim in enumerate(response.draft.claims):
            verification = verification_by_index.get(index)
            claims.append(
                {
                    "text": claim.text,
                    "claim_type": claim.claim_type,
                    "cited_chunk_ids": list(claim.cited_chunk_ids),
                    "verification_verdict": (
                        verification.verdict if verification else "not_checked"
                    ),
                    "verification_confidence": (
                        verification.confidence if verification else None
                    ),
                    "verification_reason": (
                        verification.reason if verification else None
                    ),
                    "verification_provider": (
                        verification.provider if verification else None
                    ),
                }
            )
        all_verdicts = [
            str(claim["verification_verdict"]).lower() for claim in claims
        ]
        cited_claim_verdicts = [
            str(claim["verification_verdict"]).lower()
            for claim in claims
            if claim["cited_chunk_ids"]
        ]
        if not citations:
            grounding_status = "NO_KNOWLEDGE"
        elif any(
            verdict in {"unsupported", "uncertain"} for verdict in all_verdicts
        ):
            grounding_status = "UNSUPPORTED"
        elif not cited_claim_verdicts or any(
            verdict != "supported" for verdict in cited_claim_verdicts
        ):
            grounding_status = "UNVERIFIED"
        else:
            grounding_status = "GROUNDED"
        return DraftResult(
            text=response.draft.text,
            citations=citations,
            claims=claims,
            provider=response.provider,
            model=response.model,
            fallback_used=response.fallback_used,
            grounding_status=grounding_status,
        )

