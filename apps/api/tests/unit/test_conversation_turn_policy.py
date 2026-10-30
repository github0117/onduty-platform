from ticket_agent.customer_service.turns import (
    _can_complete_grounded_turn,
)
from ticket_agent.tickets.domain import RiskLevel
from ticket_agent.tickets.models import Ticket

AUTO_SEND_GATE = {"decision": "AUTO_SEND", "reasons": []}
HUMAN_REVIEW_GATE = {"decision": "HUMAN_REVIEW", "reasons": ["HIGH_RISK"]}


def test_low_risk_grounded_answer_completes_turn() -> None:
    ticket = Ticket(
        category_primary="product_howto",
        risk_level=RiskLevel.R0,
        needs_human=False,
    )

    assert _can_complete_grounded_turn(ticket, "GROUNDED", AUTO_SEND_GATE) is True


def test_ungrounded_or_human_turn_stays_open() -> None:
    ungrounded = Ticket(
        category_primary="product_howto",
        risk_level=RiskLevel.R0,
        needs_human=False,
    )
    human_review = Ticket(
        category_primary="ecommerce_aftersales",
        risk_level=RiskLevel.R1,
        needs_human=True,
    )
    high_risk = Ticket(
        category_primary="product_howto",
        risk_level=RiskLevel.R2,
        needs_human=False,
    )

    assert (
        _can_complete_grounded_turn(
            ungrounded, "NO_KNOWLEDGE", AUTO_SEND_GATE
        )
        is False
    )
    assert (
        _can_complete_grounded_turn(
            human_review, "GROUNDED", AUTO_SEND_GATE
        )
        is False
    )
    assert (
        _can_complete_grounded_turn(high_risk, "GROUNDED", AUTO_SEND_GATE)
        is False
    )


def test_ticket_completion_requires_auto_send_gate() -> None:
    ticket = Ticket(
        category_primary="product_howto",
        risk_level=RiskLevel.R0,
        needs_human=False,
    )

    assert (
        _can_complete_grounded_turn(ticket, "GROUNDED", HUMAN_REVIEW_GATE)
        is False
    )
    # A turn recorded before the gate existed fails closed: a human sends it.
    assert _can_complete_grounded_turn(ticket, "GROUNDED", None) is False
