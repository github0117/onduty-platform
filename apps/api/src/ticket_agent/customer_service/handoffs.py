"""Employee handoff: what the next employee inherits.

Switching the employee of a conversation used to be a silent column update, so
the next turn started from a raw message window and could not tell which facts
had already been established. A handoff records the predecessor, the successor
and a deterministic summary, and the next turn's context assembly reads it.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.context import MemorySnapshot, load_memory
from ticket_agent.customer_service.models import (
    ConversationHandoff,
    ConversationTurn,
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.customer_service.turn_events import record_turn_event
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.shared.errors import ApiProblem

HANDOFF_KINDS = {
    "AUTO_REROUTE",
    "OPERATOR_SWITCH",
    "HUMAN_TAKEOVER",
    "HUMAN_RETURN",
}
HANDOFF_REASONS = {
    "TOPIC_CHANGED",
    "CAPABILITY_GAP",
    "MANUAL",
    "ESCALATION",
    # The buyer asked for another department in so many words.
    "EXPLICIT_REQUEST",
    # The same other employee was recommended on several messages in a row.
    "SUSTAINED_TOPIC",
    # The entry's employee pool no longer contains the current employee.
    "ENTRY_SCOPE_CHANGED",
}


def latest_turn(
    session: Session,
    conversation_id: UUID,
) -> ConversationTurn | None:
    return session.scalar(
        select(ConversationTurn)
        .where(ConversationTurn.conversation_id == conversation_id)
        .order_by(ConversationTurn.sequence.desc())
        .limit(1)
    )


def latest_human_message(
    session: Session,
    conversation_id: UUID,
) -> CustomerMessage | None:
    """The newest reply a human typed, if any.

    Digital answers are attributed to ``digital_employee``; anything else on
    the assistant side was written by a person through the workbench.
    """
    return session.scalar(
        select(CustomerMessage)
        .where(
            CustomerMessage.conversation_id == conversation_id,
            CustomerMessage.role == "ASSISTANT",
            CustomerMessage.created_by.is_not(None),
            CustomerMessage.created_by != "digital_employee",
        )
        .order_by(CustomerMessage.sequence.desc())
        .limit(1)
    )


def build_handoff_summary(
    session: Session,
    *,
    conversation_id: UUID,
    from_turn: ConversationTurn | None,
    memory: MemorySnapshot | None = None,
    human_message: CustomerMessage | None = None,
) -> dict[str, object]:
    """Build the handoff summary from stored state only, never from a model."""
    snapshot = memory or load_memory(session, conversation_id)
    confirmed_facts: list[dict[str, object]] = []
    open_actions: list[dict[str, object]] = []
    commitments: list[dict[str, object]] = []
    pending_questions: list[str] = []
    if snapshot is not None:
        for key, fact in snapshot.facts.items():
            confirmed_facts.append(
                {
                    "key": key,
                    "value": fact.get("value"),
                    "source_turn_id": fact.get("source_turn_id"),
                }
            )
        open_actions = [
            {
                "summary": action.get("summary"),
                "owner": action.get("owner", "employee"),
                "status": action.get("status", "open"),
            }
            for action in snapshot.open_actions
        ]
        commitments = [
            {
                "text": commitment.get("text"),
                "employee_id": commitment.get("made_by_employee_id"),
            }
            for commitment in snapshot.commitments
        ]
        pending_questions = list(snapshot.pending_questions)

    last_answer: dict[str, object] | None = None
    unverified: list[str] = []
    if from_turn is not None:
        if from_turn.assistant_message_id is not None:
            message = session.get(
                CustomerMessage,
                from_turn.assistant_message_id,
            )
            if message is not None:
                last_answer = {
                    "turn_id": str(from_turn.id),
                    "text": message.content,
                    "citations": [
                        {
                            "chunk_id": citation.get("chunk_id"),
                            "title": citation.get("title"),
                        }
                        for citation in from_turn.citations_json
                        if isinstance(citation, dict)
                    ],
                }
        status = from_turn.grounding_status
        if status and status != "GROUNDED":
            unverified.append(f"上一轮回答未核验（{status}）")

    if human_message is not None:
        # A human answered while owning the conversation. The employee that
        # takes it back must treat that reply as the latest thing said on its
        # behalf, not as its own answer.
        last_answer = {
            "turn_id": None,
            "text": human_message.content,
            "citations": [],
            "by": "human",
        }

    return {
        "confirmed_facts": confirmed_facts,
        "open_actions": open_actions,
        "commitments": commitments,
        "last_answer": last_answer,
        "pending_questions": pending_questions,
        "unverified": unverified,
    }


def create_handoff(
    session: Session,
    *,
    conversation: CustomerConversation,
    from_turn: ConversationTurn | None,
    to_employee: DigitalEmployee | None,
    kind: str,
    reason_code: str,
    actor_id: str,
    correlation_id: str | None = None,
    from_employee_id: UUID | None = None,
    human_message: CustomerMessage | None = None,
    extra_summary: dict[str, object] | None = None,
    dedupe: bool = True,
) -> ConversationHandoff:
    """Record one handoff. Idempotent per source turn.

    ``from_employee_id`` is only needed when the caller has already moved the
    conversation to the new employee; otherwise the conversation's current
    employee is the one handing over. A ``HUMAN_RETURN`` has no employee on
    the giving side: a person is handing it back.

    ``dedupe=False`` is for takeover/return, where the caller has already
    established that this is a new human cycle; the per-turn key would merge
    a second cycle with the first one.
    """
    if kind not in HANDOFF_KINDS:
        raise ApiProblem(
            status_code=400,
            code="INVALID_HANDOFF_KIND",
            title="Invalid handoff kind",
            detail=f"Handoff kind {kind} is not supported.",
        )
    if reason_code not in HANDOFF_REASONS:
        raise ApiProblem(
            status_code=400,
            code="INVALID_HANDOFF_REASON",
            title="Invalid handoff reason",
            detail=f"Handoff reason {reason_code} is not supported.",
        )
    if (
        to_employee is not None
        and to_employee.business_unit_id != conversation.business_unit_id
    ):
        raise ApiProblem(
            status_code=400,
            code="HANDOFF_EMPLOYEE_UNIT_MISMATCH",
            title="Employee belongs to another business unit",
            detail="A conversation can only be handed to an employee of its own business unit.",
        )
    from_turn_id = from_turn.id if from_turn is not None else None
    to_employee_id = to_employee.id if to_employee is not None else None
    if dedupe and from_turn_id is not None:
        # Same source turn and same target: this is a retry of one transfer.
        # A different target is a new transfer and gets its own record.
        existing = session.scalar(
            select(ConversationHandoff).where(
                ConversationHandoff.from_turn_id == from_turn_id,
                ConversationHandoff.to_employee_id == to_employee_id,
            )
        )
        if existing is not None:
            return existing
    summary = build_handoff_summary(
        session,
        conversation_id=conversation.id,
        from_turn=from_turn,
        human_message=human_message,
    )
    if extra_summary:
        summary.update(extra_summary)
    handoff = ConversationHandoff(
        conversation_id=conversation.id,
        business_unit_id=conversation.business_unit_id,
        from_turn_id=from_turn_id,
        from_employee_id=(
            None
            if kind == "HUMAN_RETURN"
            else (
                from_employee_id
                if from_employee_id is not None
                else conversation.employee_id
            )
        ),
        to_employee_id=to_employee_id,
        kind=kind,
        reason_code=reason_code,
        summary_json=summary,
        created_by=actor_id,
    )
    session.add(handoff)
    session.flush()
    if from_turn is not None:
        record_turn_event(
            session,
            from_turn,
            event_type="HANDOFF_CREATED",
            actor_id=actor_id,
            correlation_id=correlation_id,
            payload={
                "handoff_id": str(handoff.id),
                "kind": kind,
                "reason_code": reason_code,
                "from_employee_id": (
                    str(handoff.from_employee_id)
                    if handoff.from_employee_id
                    else None
                ),
                "to_employee_id": (
                    str(handoff.to_employee_id)
                    if handoff.to_employee_id
                    else None
                ),
            },
        )
    return handoff
