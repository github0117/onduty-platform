from sqlalchemy.orm import Session

from ticket_agent.tickets.domain import RiskLevel
from ticket_agent.tickets.drafts import DraftResult
from ticket_agent.tickets.models import Ticket
from ticket_agent.workflow.service import WorkflowService

ALLOWED_TOOLS = [
    "ticket.read",
    "knowledge.search",
    "draft.create",
    "ticket.sync",
]


def _ticket() -> Ticket:
    return Ticket(
        category_primary="ecommerce_presales",
        risk_level=RiskLevel.R0,
        confidence=0.94,
        needs_human=False,
    )


def _draft(
    *,
    verdict: str = "supported",
    fallback_used: bool = False,
    grounding_status: str = "GROUNDED",
    cited_claim: bool = True,
    citations: bool = True,
) -> DraftResult:
    return DraftResult(
        text="保温杯内胆为 316 不锈钢。",
        citations=(
            [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "document-1",
                    "space_id": "space-1",
                    "title": "保温杯参数",
                    "version": "1.0",
                }
            ]
            if citations
            else []
        ),
        claims=[
            {
                "text": "保温杯内胆为 316 不锈钢。",
                "claim_type": "instruction",
                "cited_chunk_ids": ["chunk-1"] if cited_claim else [],
                "verification_verdict": verdict,
                "verification_confidence": 0.9,
                "verification_reason": "test",
                "verification_provider": "test",
            }
        ],
        provider="local",
        model="test",
        fallback_used=fallback_used,
        grounding_status=grounding_status,
    )


def _decision(draft: DraftResult) -> tuple[bool, str]:
    with Session() as session:
        return WorkflowService(session)._auto_reply_decision(
            _ticket(),
            draft,
            ALLOWED_TOOLS,
        )


def test_auto_reply_requires_sync_tool_authorization() -> None:
    with Session() as session:
        eligible, reason = WorkflowService(session)._auto_reply_decision(
            _ticket(),
            _draft(),
            ["ticket.read", "knowledge.search", "draft.create"],
        )

    assert eligible is False
    assert reason == "AUTO_REPLY_SYNC_NOT_AUTHORIZED"


def test_auto_reply_rejects_fallback_drafts() -> None:
    eligible, reason = _decision(_draft(fallback_used=True))

    assert eligible is False
    assert reason == "AUTO_REPLY_FALLBACK_USED"


def test_auto_reply_rejects_unverified_claims() -> None:
    eligible, reason = _decision(
        _draft(verdict="not_checked", grounding_status="UNVERIFIED")
    )

    assert eligible is False
    assert reason == "AUTO_REPLY_CLAIM_UNVERIFIED"


def test_auto_reply_rejects_unsupported_claims() -> None:
    eligible, reason = _decision(
        _draft(verdict="unsupported", grounding_status="UNSUPPORTED")
    )

    assert eligible is False
    assert reason == "AUTO_REPLY_CLAIM_NOT_SUPPORTED"


def test_auto_reply_rejects_unsupported_uncited_claims() -> None:
    eligible, reason = _decision(
        _draft(
            cited_claim=False,
            verdict="unsupported",
            grounding_status="UNSUPPORTED",
        )
    )

    assert eligible is False
    assert reason == "AUTO_REPLY_CLAIM_NOT_SUPPORTED"


def test_auto_reply_requires_a_cited_claim() -> None:
    eligible, reason = _decision(
        _draft(cited_claim=False, grounding_status="UNVERIFIED")
    )

    assert eligible is False
    assert reason == "AUTO_REPLY_NO_VERIFIED_CLAIM"


def test_auto_reply_allows_supported_cited_claims() -> None:
    eligible, reason = _decision(_draft())

    assert eligible is True
    assert reason == "LOW_RISK_GROUNDED_PRESALES"
