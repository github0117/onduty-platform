from ticket_agent.customer_service.turns import (
    _can_complete_grounded_turn,
)
from ticket_agent.tickets.domain import RiskLevel
from ticket_agent.tickets.models import Ticket


def test_low_risk_grounded_answer_completes_turn() -> None:
    ticket = Ticket(
        category_primary="product_howto",
        risk_level=RiskLevel.R0,
        needs_human=False,
    )

    assert _can_complete_grounded_turn(ticket, "GROUNDED") is True


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

    assert _can_complete_grounded_turn(ungrounded, "NO_KNOWLEDGE") is False
    assert _can_complete_grounded_turn(human_review, "GROUNDED") is False
    assert _can_complete_grounded_turn(high_risk, "GROUNDED") is False
