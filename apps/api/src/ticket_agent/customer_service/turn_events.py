"""Turn state transitions and the append-only turn event log.

Every status change goes through :func:`transition_turn`, mirroring
``tickets/transitions.py``: legal edges are declared in ``domain.py``, illegal
jumps raise a 409 instead of silently rewriting history, and each successful
edge appends one row to ``conversation_turn_events``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.domain import (
    ALLOWED_TURN_TRANSITIONS,
    TERMINAL_TURN_STATUSES,
    TurnStatus,
    parse_turn_status,
)
from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
    CustomerConversation,
)
from ticket_agent.shared.db import run_with_deadlock_retry
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings

DEFAULT_TURN_EVENT_TYPE: dict[TurnStatus, str] = {
    TurnStatus.PENDING: "TURN_RETRY_SCHEDULED",
    TurnStatus.RUNNING: "TURN_STARTED",
    TurnStatus.COMPLETED: "TURN_COMPLETED",
    TurnStatus.NEEDS_HUMAN: "TURN_NEEDS_HUMAN",
    TurnStatus.FAILED_RETRYABLE: "TURN_FAILED",
    TurnStatus.FAILED_TERMINAL: "TURN_FAILED_TERMINAL",
    TurnStatus.CANCELLED: "TURN_CANCELLED",
}


def record_turn_event(
    session: Session,
    turn: ConversationTurn,
    *,
    event_type: str,
    actor_id: str,
    actor_type: str = "SERVICE",
    correlation_id: str | None = None,
    stage_label: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ConversationTurnEvent:
    """Append one event for ``turn``, serialising the sequence on the turn row.

    Callers usually hold the turn lock already (state transitions); a writer
    that does not — a supervisor handing the conversation over while a worker
    is mid-turn, for example — would otherwise compute the same next sequence
    as the worker and fail on the unique constraint. Taking the row lock here
    makes the sequence single-writer per turn regardless of the caller.
    """
    if turn.id is None:
        session.flush()
    session.scalar(
        select(ConversationTurn.id)
        .where(ConversationTurn.id == turn.id)
        .with_for_update()
    )
    conversation = session.get(CustomerConversation, turn.conversation_id)
    if conversation is None:
        raise ApiProblem(
            status_code=409,
            code="CONVERSATION_TURN_ORPHANED",
            title="Conversation turn has no conversation",
            detail=f"Conversation turn {turn.id} is not attached to a conversation.",
        )
    next_sequence = (
        session.scalar(
            select(func.max(ConversationTurnEvent.sequence)).where(
                ConversationTurnEvent.turn_id == turn.id
            )
        )
        or 0
    ) + 1
    event = ConversationTurnEvent(
        turn_id=turn.id,
        conversation_id=turn.conversation_id,
        business_unit_id=conversation.business_unit_id,
        sequence=next_sequence,
        event_type=event_type,
        status=turn.status,
        stage_label=stage_label if stage_label is not None else turn.stage_label,
        actor_type=actor_type,
        actor_id=actor_id,
        correlation_id=correlation_id or turn.correlation_id,
        payload_json=payload or {},
    )
    session.add(event)
    # Flush so the next sequence lookup sees this row; callers hold the turn
    # row lock, so no other writer can take the same sequence.
    session.flush()
    return event


def transition_turn(
    session: Session,
    turn: ConversationTurn,
    target: TurnStatus,
    *,
    reason_code: str,
    actor_id: str,
    actor_type: str = "SERVICE",
    correlation_id: str | None = None,
    event_type: str | None = None,
    stage_label: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_version: int | None = None,
    allow_terminal: bool = False,
) -> bool:
    """Move a turn through an allowed edge and log it.

    Returns False when the turn is already in ``target`` (idempotent replay).
    Raises 409 for an unlisted edge or a stale ``expected_version``.
    """
    current = parse_turn_status(turn.status)
    if expected_version is not None and turn.version != expected_version:
        raise ApiProblem(
            status_code=409,
            code="CONVERSATION_TURN_VERSION_CONFLICT",
            title="Conversation turn was modified",
            detail=(
                f"Expected version {expected_version}, found {turn.version}."
            ),
        )
    if current == target:
        return False
    if current in TERMINAL_TURN_STATUSES and not allow_terminal:
        raise ApiProblem(
            status_code=409,
            code="INVALID_TURN_TRANSITION",
            title="Turn transition is not allowed",
            detail=(
                f"Cannot move turn from {current.value} to {target.value}: "
                f"{current.value} is terminal."
            ),
        )
    if target not in ALLOWED_TURN_TRANSITIONS[current]:
        raise ApiProblem(
            status_code=409,
            code="INVALID_TURN_TRANSITION",
            title="Turn transition is not allowed",
            detail=(
                f"Cannot move turn from {current.value} to {target.value}."
            ),
        )
    turn.status = target.value
    turn.version += 1
    if stage_label is not None:
        turn.stage_label = stage_label
    event_payload = dict(payload or {})
    event_payload.setdefault("from_status", current.value)
    event_payload.setdefault("to_status", target.value)
    event_payload.setdefault("reason_code", reason_code)
    record_turn_event(
        session,
        turn,
        event_type=event_type or DEFAULT_TURN_EVENT_TYPE[target],
        actor_id=actor_id,
        actor_type=actor_type,
        correlation_id=correlation_id,
        stage_label=turn.stage_label,
        payload=event_payload,
    )
    return True


def list_turn_events(
    session: Session,
    *,
    turn_id: UUID,
    after_sequence: int | None = None,
    limit: int | None = None,
) -> list[ConversationTurnEvent]:
    statement = select(ConversationTurnEvent).where(
        ConversationTurnEvent.turn_id == turn_id
    )
    if after_sequence is not None:
        statement = statement.where(
            ConversationTurnEvent.sequence > after_sequence
        )
    statement = statement.order_by(ConversationTurnEvent.sequence)
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def new_lease(seconds: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(seconds=seconds)


def reclaim_stuck_turns(
    session: Session,
    *,
    limit: int,
    now: datetime | None = None,
    actor_id: str = "digital_employee.reclaimer",
) -> list[UUID]:
    """Recover turns whose worker died before finishing.

    A PENDING turn with an expired lease never reached a worker: count the
    dispatch attempt. A RUNNING turn with an expired lease was already counted
    when it started. Both go back to PENDING while attempts remain, then to
    FAILED_TERMINAL so the beat task cannot spin on a poisoned turn forever.

    Returns the ids that were put back in PENDING for re-dispatch.
    """
    return run_with_deadlock_retry(
        session,
        "turn reclaim batch",
        lambda: _reclaim_turns_once(
            session,
            limit=limit,
            now=now,
            actor_id=actor_id,
        ),
    )


def _reclaim_turns_once(
    session: Session,
    *,
    limit: int,
    now: datetime | None,
    actor_id: str,
) -> list[UUID]:
    settings = get_settings()
    cutoff = now or datetime.now(UTC)
    lease_seconds = settings.conversation_turn_lease_seconds
    max_attempts = settings.conversation_turn_max_attempts
    stuck = list(
        session.scalars(
            select(ConversationTurn)
            .where(
                ConversationTurn.status.in_(
                    [TurnStatus.PENDING.value, TurnStatus.RUNNING.value]
                ),
                ConversationTurn.lease_expires_at.is_not(None),
                ConversationTurn.lease_expires_at < cutoff,
            )
            .order_by(ConversationTurn.lease_expires_at)
            .limit(limit)
            .with_for_update()
        )
    )
    retry_ids: list[UUID] = []
    for turn in stuck:
        current = parse_turn_status(turn.status)
        if current == TurnStatus.PENDING:
            turn.attempt_count += 1
        if turn.attempt_count >= max_attempts:
            transition_turn(
                session,
                turn,
                TurnStatus.FAILED_TERMINAL,
                reason_code="TURN_LEASE_EXPIRED_MAX_ATTEMPTS",
                actor_id=actor_id,
                event_type="TURN_RECLAIMED",
                stage_label="处理超时，已停止重试",
                payload={"attempt_count": turn.attempt_count},
            )
            continue
        if current == TurnStatus.RUNNING:
            transition_turn(
                session,
                turn,
                TurnStatus.FAILED_RETRYABLE,
                reason_code="TURN_LEASE_EXPIRED",
                actor_id=actor_id,
                event_type="TURN_RECLAIMED",
                stage_label="处理超时，等待重试",
                payload={"attempt_count": turn.attempt_count},
            )
            transition_turn(
                session,
                turn,
                TurnStatus.PENDING,
                reason_code="TURN_LEASE_EXPIRED",
                actor_id=actor_id,
                stage_label="已排队重试",
                payload={"attempt_count": turn.attempt_count},
            )
        else:
            record_turn_event(
                session,
                turn,
                event_type="TURN_RETRY_SCHEDULED",
                actor_id=actor_id,
                stage_label="已排队重试",
                payload={
                    "reason_code": "TURN_LEASE_EXPIRED",
                    "attempt_count": turn.attempt_count,
                },
            )
        turn.lease_expires_at = new_lease(lease_seconds, now=cutoff)
        retry_ids.append(turn.id)
    session.commit()
    return retry_ids
