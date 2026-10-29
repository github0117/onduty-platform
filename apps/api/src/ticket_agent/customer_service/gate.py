"""Accuracy gate: decide whether one reply may be sent without a human.

M2 made "did the Skill's required steps happen?" a runtime question. This
module answers the other half: "is the evidence behind this text strong enough
to leave the building unattended?" It is a pure function over the draft, the
Skill completion verdict and the ticket risk so the same inputs always produce
the same decision and the decision can be replayed from ``gate_json``.

The gate deliberately fails closed: an unknown status, an unchecked claim or a
missing completion verdict never reaches ``AUTO_SEND``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

GATE_VERSION = 1

GateDecision = Literal["AUTO_SEND", "HUMAN_REVIEW", "BLOCK"]

AUTO_SEND: GateDecision = "AUTO_SEND"
HUMAN_REVIEW: GateDecision = "HUMAN_REVIEW"
BLOCK: GateDecision = "BLOCK"

# Statuses whose text is fixed or explicitly does not need evidence. The
# answer still goes through the connector's own switch, but the gate does not
# hold it for a human.
FIXED_TEXT_STATUSES = {"POLICY_BLOCKED"}
NO_EVIDENCE_REQUIRED_STATUSES = {"NOT_REQUIRED"}
HUMAN_ONLY_STATUSES = {"APPROVAL_REQUIRED"}

HIGH_RISK_LEVELS = {"R2", "R3"}

# Claim types that make a policy/instruction promise. Every one of them must
# point at evidence before the answer can auto-send.
CITED_CLAIM_TYPES = {"policy", "instruction"}


@dataclass(frozen=True)
class GateContext:
    grounding_status: str
    claims: Sequence[dict[str, Any]]
    citations: Sequence[dict[str, Any]]
    risk_level: str | None
    ticket_needs_human: bool
    skill_completion: dict[str, Any] | None
    path: str


def _verdict(claim: dict[str, Any]) -> str:
    return str(claim.get("verification_verdict", "not_checked")).lower()


def _has_citation(claim: dict[str, Any]) -> bool:
    cited = claim.get("cited_chunk_ids")
    if isinstance(cited, (list, tuple, set)):
        return bool(cited)
    return bool(cited)


def evaluate_gate(context: GateContext) -> dict[str, Any]:
    status = (context.grounding_status or "").upper()
    verdicts = [_verdict(claim) for claim in context.claims]
    cited_claims = [claim for claim in context.claims if _has_citation(claim)]
    cited_verdicts = [_verdict(claim) for claim in cited_claims]
    unsupported_count = sum(1 for verdict in verdicts if verdict == "unsupported")
    uncertain_count = sum(1 for verdict in verdicts if verdict == "uncertain")
    unchecked_cited_count = sum(1 for verdict in cited_verdicts if verdict != "supported")
    uncited_policy_count = sum(
        1
        for claim in context.claims
        if str(claim.get("claim_type", "")).lower() in CITED_CLAIM_TYPES
        and not _has_citation(claim)
    )
    numeric_violation_count = sum(
        1
        for claim in context.claims
        if _verdict(claim) == "unsupported"
        and str(claim.get("verification_reason", "")).upper()
        == "UNSUPPORTED_NUMERIC_CLAIM"
    )
    skill_complete = (
        None
        if context.skill_completion is None
        else bool(context.skill_completion.get("complete"))
    )
    high_risk = context.risk_level in HIGH_RISK_LEVELS

    reasons: list[str] = []
    if status in FIXED_TEXT_STATUSES or status in NO_EVIDENCE_REQUIRED_STATUSES:
        reasons = []
    elif status in HUMAN_ONLY_STATUSES:
        reasons.append("APPROVAL_REQUIRED")
    else:
        if status != "GROUNDED":
            reasons.append(f"GROUNDING_{status or 'UNKNOWN'}")
        if unsupported_count:
            reasons.append("UNSUPPORTED_CLAIM")
        if uncertain_count:
            reasons.append("UNCERTAIN_CLAIM")
        if unchecked_cited_count:
            reasons.append("UNCHECKED_CITED_CLAIM")
        if uncited_policy_count:
            reasons.append("POLICY_CLAIM_WITHOUT_CITATION")
        if numeric_violation_count:
            reasons.append("UNSUPPORTED_NUMERIC_CLAIM")
        if skill_complete is False:
            reasons.append("SKILL_INCOMPLETE")
        if high_risk:
            reasons.append("HIGH_RISK")
        if context.ticket_needs_human:
            reasons.append("TICKET_NEEDS_HUMAN")

    auto_send = not reasons and status in (
        FIXED_TEXT_STATUSES | NO_EVIDENCE_REQUIRED_STATUSES | {"GROUNDED"}
    )
    decision: GateDecision = AUTO_SEND if auto_send else HUMAN_REVIEW

    return {
        "version": GATE_VERSION,
        "decision": decision,
        "path": context.path,
        "grounding_status": status,
        "reasons": reasons,
        "checks": {
            "citation_count": len(context.citations),
            "claim_count": len(context.claims),
            "unsupported_claim_count": unsupported_count,
            "uncertain_claim_count": uncertain_count,
            "unchecked_cited_claim_count": unchecked_cited_count,
            "uncited_policy_claim_count": uncited_policy_count,
            "unsupported_numeric_claim_count": numeric_violation_count,
            "skill_complete": skill_complete,
            "risk_level": context.risk_level,
            "ticket_needs_human": context.ticket_needs_human,
        },
    }
