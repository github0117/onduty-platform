from ticket_agent.customer_service.gate import GateContext, evaluate_gate
from ticket_agent.customer_service.suggestions import _tool_evidence_claims


def _claim(
    *,
    verdict: str = "supported",
    claim_type: str = "instruction",
    cited: bool = True,
    reason: str = "test",
) -> dict[str, object]:
    return {
        "text": "保温杯内胆为 316 不锈钢。",
        "claim_type": claim_type,
        "cited_chunk_ids": ["chunk-1"] if cited else [],
        "verification_verdict": verdict,
        "verification_confidence": 0.9,
        "verification_reason": reason,
        "verification_provider": "test",
    }


def _gate(
    *,
    status: str = "GROUNDED",
    claims: list[dict[str, object]] | None = None,
    citations: bool = True,
    risk: str | None = "R1",
    needs_human: bool = False,
    skill_complete: bool | None = True,
) -> dict[str, object]:
    return evaluate_gate(
        GateContext(
            grounding_status=status,
            claims=claims if claims is not None else [_claim()],
            citations=(
                [{"chunk_id": "chunk-1", "title": "参数"}] if citations else []
            ),
            risk_level=risk,
            ticket_needs_human=needs_human,
            skill_completion=(
                None if skill_complete is None else {"complete": skill_complete}
            ),
            path="llm_draft",
        )
    )


def test_grounded_supported_claim_auto_sends() -> None:
    gate = _gate()

    assert gate["decision"] == "AUTO_SEND"
    assert gate["reasons"] == []
    assert gate["version"] == 1
    assert gate["checks"]["claim_count"] == 1
    assert gate["checks"]["unsupported_claim_count"] == 0


def test_unverified_answer_needs_human() -> None:
    gate = _gate(status="UNVERIFIED", claims=[_claim(verdict="not_checked")])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "GROUNDING_UNVERIFIED" in gate["reasons"]
    assert "UNCHECKED_CITED_CLAIM" in gate["reasons"]
    assert gate["checks"]["unchecked_cited_claim_count"] == 1


def test_unsupported_claim_needs_human() -> None:
    gate = _gate(status="UNSUPPORTED", claims=[_claim(verdict="unsupported")])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "UNSUPPORTED_CLAIM" in gate["reasons"]


def test_uncertain_claim_needs_human() -> None:
    gate = _gate(status="UNVERIFIED", claims=[_claim(verdict="uncertain")])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "UNCERTAIN_CLAIM" in gate["reasons"]


def test_policy_claim_without_citation_needs_human() -> None:
    # Status is GROUNDED, so grounding alone would let this through; the gate
    # exists to catch exactly this shape.
    gate = _gate(claims=[_claim(claim_type="policy", cited=False)])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert gate["reasons"] == ["POLICY_CLAIM_WITHOUT_CITATION"]
    assert gate["checks"]["uncited_policy_claim_count"] == 1


def test_uncited_instruction_claim_needs_human() -> None:
    gate = _gate(claims=[_claim(claim_type="instruction", cited=False)])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "POLICY_CLAIM_WITHOUT_CITATION" in gate["reasons"]


def test_unsupported_numeric_claim_is_reported() -> None:
    gate = _gate(
        status="UNSUPPORTED",
        claims=[_claim(verdict="unsupported", reason="UNSUPPORTED_NUMERIC_CLAIM")],
    )

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "UNSUPPORTED_NUMERIC_CLAIM" in gate["reasons"]
    assert gate["checks"]["unsupported_numeric_claim_count"] == 1


def test_incomplete_skill_needs_human() -> None:
    gate = _gate(skill_complete=False)

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "SKILL_INCOMPLETE" in gate["reasons"]
    assert gate["checks"]["skill_complete"] is False


def test_high_risk_needs_human() -> None:
    assert "HIGH_RISK" in _gate(risk="R2")["reasons"]
    assert "HIGH_RISK" in _gate(risk="R3")["reasons"]
    assert "HIGH_RISK" not in _gate(risk="R0")["reasons"]


def test_ticket_needs_human_blocks_auto_send() -> None:
    gate = _gate(needs_human=True)

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "TICKET_NEEDS_HUMAN" in gate["reasons"]


def test_no_knowledge_needs_human() -> None:
    gate = _gate(status="NO_KNOWLEDGE", claims=[])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert "GROUNDING_NO_KNOWLEDGE" in gate["reasons"]


def test_unknown_status_fails_closed() -> None:
    gate = _gate(status="SOMETHING_NEW", claims=[])

    assert gate["decision"] == "HUMAN_REVIEW"
    assert gate["reasons"] == ["GROUNDING_SOMETHING_NEW"]


def test_policy_blocked_is_fixed_text_and_auto_sends() -> None:
    gate = _gate(status="POLICY_BLOCKED", claims=[], citations=False)

    assert gate["decision"] == "AUTO_SEND"
    assert gate["reasons"] == []


def test_not_required_is_no_evidence_and_auto_sends() -> None:
    gate = _gate(status="NOT_REQUIRED", claims=[], citations=False)

    assert gate["decision"] == "AUTO_SEND"


def test_approval_required_is_never_auto_sent() -> None:
    gate = _gate(status="APPROVAL_REQUIRED", claims=[], citations=False)

    assert gate["decision"] == "HUMAN_REVIEW"
    assert gate["reasons"] == ["APPROVAL_REQUIRED"]


def test_missing_skill_completion_is_not_a_pass() -> None:
    gate = _gate(skill_complete=None)

    assert gate["checks"]["skill_complete"] is None
    assert gate["decision"] == "AUTO_SEND"


def test_tool_evidence_accepts_numbers_present_in_tool_result() -> None:
    claims = _tool_evidence_claims(
        "签收后 7 天内可申请退款。",
        "chunk-1",
        "售后政策：签收后 7 天内可申请退款。",
    )

    assert claims[0]["verification_verdict"] == "supported"


def test_tool_evidence_rejects_invented_numbers() -> None:
    claims = _tool_evidence_claims(
        "签收后 30 天内可申请退款。",
        "chunk-1",
        "售后政策：签收后 7 天内可申请退款。",
    )

    assert claims[0]["verification_verdict"] == "unsupported"
    assert claims[0]["verification_reason"] == "UNSUPPORTED_NUMERIC_CLAIM"
