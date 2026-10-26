from sqlalchemy.orm import Session

from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.domain import (
    ALLOWED_WORKFLOW_TRANSITIONS,
    TERMINAL_WORKFLOW_STATES,
    WorkflowState,
)
from ticket_agent.tickets.models import Ticket, WorkflowTransition


def transition_ticket(
    session: Session,
    ticket: Ticket,
    target: WorkflowState,
    *,
    reason_code: str,
    actor_type: str = "SERVICE",
    actor_id: str = "digital_agent.ticket.v1",
    allow_terminal: bool = False,
) -> bool:
    """Move a ticket through an allowed workflow edge.

    Returns False when the ticket is already in the target state or when an
    automated caller tries to leave a terminal state. Illegal jumps raise so a
    programming error cannot silently corrupt the workflow history.
    """
    current = WorkflowState(ticket.workflow_state)
    if current == target:
        return False
    if current in TERMINAL_WORKFLOW_STATES and not allow_terminal:
        return False
    if target not in ALLOWED_WORKFLOW_TRANSITIONS[current]:
        raise ApiProblem(
            status_code=409,
            code="INVALID_WORKFLOW_TRANSITION",
            title="Workflow transition is not allowed",
            detail=(
                f"Cannot move ticket from {current.value} to {target.value}."
            ),
        )
    ticket.workflow_state = target
    session.add(
        WorkflowTransition(
            ticket_id=ticket.id,
            from_state=current,
            to_state=target,
            reason_code=reason_code,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    )
    return True
