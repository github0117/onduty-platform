from uuid import uuid4

from ticket_agent.classification.classifier import AnalysisResult
from ticket_agent.knowledge.claim_verifier import ClaimToVerify
from ticket_agent.knowledge.service import KnowledgeHit
from ticket_agent.model_gateway.types import (
    ClaimVerification,
    DraftClaim,
    DraftGenerationResponse,
    GeneratedDraft,
)
from ticket_agent.routing.policy import RoutingDecision
from ticket_agent.tickets.domain import Priority, RiskLevel
from ticket_agent.tickets.drafts import DraftResult, DraftService

ANALYSIS = AnalysisResult(
    category_primary="ecommerce_presales",
    category_secondary="category_presales",
    confidence=0.9,
    risk_level=RiskLevel.R0,
    risk_tags=[],
    reason_codes=[],
    summary="",
    needs_human=False,
    human_reason=None,
    model_provider="local",
    model_name="test",
    fallback_used=False,
)
ROUTING = RoutingDecision(
    queue_id="ECOMMERCE_PRESALES",
    priority=Priority.P3,
    needs_human=False,
    human_reason=None,
    matched_rule_id="test",
    reason_codes=[],
)


class StubGateway:
    def __init__(self, response: DraftGenerationResponse) -> None:
        self.response = response

    def generate_draft(self, **kwargs: object) -> DraftGenerationResponse:
        del kwargs
        return self.response


class StubVerifier:
    name = "stub"
    enforce = False

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.claims: list[ClaimToVerify] = []

    def verify(
        self,
        claims: list[ClaimToVerify],
    ) -> list[ClaimVerification]:
        self.claims = claims
        return [
            ClaimVerification(
                claim_index=claim.claim_index,
                verdict=self.verdict,  # type: ignore[arg-type]
                confidence=0.9,
                reason="stub",
                provider="stub",
                model=self.name,
            )
            for claim in claims
        ]


def _run(
    *,
    verdict: str | None = "supported",
    cited: bool = True,
) -> tuple[DraftResult, StubVerifier | None]:
    hit = KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        title="保温杯参数",
        version="1.0",
        content="保温杯内胆为 316 不锈钢。",
        score=0.9,
        space_id=uuid4(),
    )
    claim_ids = [str(hit.chunk_id)] if cited else []
    draft = GeneratedDraft(
        text="保温杯内胆为 316 不锈钢。",
        claims=[
            DraftClaim(
                text="保温杯内胆为 316 不锈钢。",
                claim_type="instruction",
                cited_chunk_ids=claim_ids,
            )
        ],
        cited_chunk_ids=claim_ids,
    )
    verifier = StubVerifier(verdict) if verdict is not None else None
    service = DraftService(
        gateway=StubGateway(
            DraftGenerationResponse(
                draft=draft,
                provider="stub",
                model="stub",
            )
        ),
        claim_verifier=verifier,
        use_configured_claim_verifier=False,
    )
    result = service.generate(
        subject="内胆材质",
        body="请问内胆是什么材质？",
        analysis=ANALYSIS,
        routing=ROUTING,
        knowledge_hits=[hit],
    )
    return result, verifier


def test_supported_claim_marks_draft_grounded() -> None:
    result, verifier = _run()

    assert result.grounding_status == "GROUNDED"
    assert verifier is not None
    assert verifier.claims[0].sources == ["保温杯内胆为 316 不锈钢。"]
    assert result.claims[0]["verification_verdict"] == "supported"


def test_unsupported_claim_marks_draft_unsupported() -> None:
    result, _ = _run(verdict="unsupported")

    assert result.grounding_status == "UNSUPPORTED"


def test_missing_verifier_marks_draft_unverified() -> None:
    result, verifier = _run(verdict=None)

    assert verifier is None
    assert result.grounding_status == "UNVERIFIED"
    assert result.claims[0]["verification_verdict"] == "not_checked"


def test_missing_citations_marks_draft_no_knowledge() -> None:
    result, _ = _run(cited=False)

    assert result.grounding_status == "NO_KNOWLEDGE"
