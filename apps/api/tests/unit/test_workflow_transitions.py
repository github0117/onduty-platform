from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.domain import WorkflowState
from ticket_agent.tickets.models import Ticket, WorkflowTransition
from ticket_agent.tickets.transitions import transition_ticket


def _ticket(state: WorkflowState) -> Ticket:
    return Ticket(
        id=uuid4(),
        business_unit_id="bu_demo",
        workflow_state=state,
    )


def test_transition_records_allowed_edge() -> None:
    ticket = _ticket(WorkflowState.RECEIVED)
    with Session() as session:
        applied = transition_ticket(
            session,
            ticket,
            WorkflowState.CLASSIFYING,
            reason_code="START_PROCESSING",
        )

        assert applied is True
        assert ticket.workflow_state == WorkflowState.CLASSIFYING
        transition = next(
            item
            for item in session.new
            if isinstance(item, WorkflowTransition)
        )
        assert transition.from_state == WorkflowState.RECEIVED
        assert transition.to_state == WorkflowState.CLASSIFYING
        assert transition.reason_code == "START_PROCESSING"
        assert transition.actor_id == "digital_agent.ticket.v1"


def test_transition_is_idempotent_for_same_state() -> None:
    ticket = _ticket(WorkflowState.PENDING_REVIEW)
    with Session() as session:
        applied = transition_ticket(
            session,
            ticket,
            WorkflowState.PENDING_REVIEW,
            reason_code="TURN_PENDING_REVIEW",
        )

        assert applied is False
        assert not list(session.new)


def test_automated_transition_cannot_leave_terminal_state() -> None:
    ticket = _ticket(WorkflowState.COMPLETED)
    with Session() as session:
        applied = transition_ticket(
            session,
            ticket,
            WorkflowState.RECEIVED,
            reason_code="REOPEN",
        )

        assert applied is False
        assert ticket.workflow_state == WorkflowState.COMPLETED
        assert not list(session.new)


def test_operator_can_reopen_completed_ticket() -> None:
    ticket = _ticket(WorkflowState.COMPLETED)
    with Session() as session:
        applied = transition_ticket(
            session,
            ticket,
            WorkflowState.RECEIVED,
            reason_code="NEW_BUYER_MESSAGE",
            actor_type="USER",
            actor_id="agent-1",
            allow_terminal=True,
        )

        assert applied is True
        assert ticket.workflow_state == WorkflowState.RECEIVED


def test_unlisted_transition_is_rejected() -> None:
    ticket = _ticket(WorkflowState.COMPLETED)
    with Session() as session, pytest.raises(ApiProblem) as exc_info:
        transition_ticket(
            session,
            ticket,
            WorkflowState.PENDING_REVIEW,
            reason_code="FORCE_REVIEW",
            allow_terminal=True,
        )

    assert exc_info.value.code == "INVALID_WORKFLOW_TRANSITION"
    assert ticket.workflow_state == WorkflowState.COMPLETED
