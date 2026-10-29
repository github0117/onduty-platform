from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.customer_service.domain import TurnStatus
from ticket_agent.customer_service.models import (
    ConversationTurn,
    ConversationTurnEvent,
)
from ticket_agent.customer_service.turn_events import (
    reclaim_stuck_turns,
    transition_turn,
)
from ticket_agent.customer_service.turns import process_conversation_turn
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.drafts import grounding_status_from_claims

AGENT = {"X-Actor-Id": "agent-1", "X-Actor-Role": "agent"}
SUPERVISOR = {"X-Actor-Id": "supervisor-1", "X-Actor-Role": "supervisor"}


def _small_talk_conversation(client: TestClient) -> tuple[str, str]:
    conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "turn-events-buyer",
            "channel": "enterprise_service",
        },
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    accepted = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=AGENT,
        json={"content": "你好"},
    )
    assert accepted.status_code == 202, accepted.text
    turn_id = accepted.json()["current_turn"]["id"]
    return conversation_id, turn_id


def _events(conversation_id: str, turn_id: str) -> list[dict[str, object]]:
    with SessionLocal() as session:
        return [
            {
                "event_type": event.event_type,
                "status": event.status,
                "sequence": event.sequence,
                "correlation_id": event.correlation_id,
                "payload": event.payload_json,
            }
            for event in session.scalars(
                select(ConversationTurnEvent)
                .where(ConversationTurnEvent.turn_id == UUID(turn_id))
                .order_by(ConversationTurnEvent.sequence)
            )
        ]


def _as_aware(value: datetime) -> datetime:
    # SQLite drops tzinfo; PostgreSQL keeps it.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _force_stuck_turn(
    turn_id: str,
    *,
    status: str = "RUNNING",
    attempt_count: int = 1,
    lease_offset_seconds: int = -60,
) -> None:
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        turn.status = status
        turn.attempt_count = attempt_count
        turn.lease_expires_at = datetime.now(UTC) + timedelta(
            seconds=lease_offset_seconds
        )
        session.commit()


def test_turn_lifecycle_events_are_ordered_and_queryable(
    client: TestClient,
) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)

    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{turn_id}/events",
        headers=AGENT,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["conversation_id"] == conversation_id
    assert payload["turn_id"] == turn_id
    events = payload["events"]
    assert [event["event_type"] for event in events] == [
        "TURN_CREATED",
        "TURN_STARTED",
        "TURN_COMPLETED",
    ]
    assert [event["status"] for event in events] == [
        "PENDING",
        "RUNNING",
        "COMPLETED",
    ]
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert all(event["correlation_id"] for event in events)
    assert events[-1]["payload"]["reason_code"] == "SMALL_TALK_ANSWERED"

    detail = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}",
        headers=AGENT,
    )
    turn = detail.json()["current_turn"]
    assert turn["status"] == "COMPLETED"
    assert turn["version"] == 3
    assert turn["attempt_count"] == 1
    assert turn["correlation_id"]


def test_turn_events_reject_foreign_turn_and_foreign_tenant(
    client: TestClient,
) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)
    other_conversation = client.post(
        "/api/v1/customer-service/conversations",
        headers=AGENT,
        json={
            "business_unit_id": "bu_demo",
            "requester_ref": "other-buyer",
            "channel": "enterprise_service",
        },
    )
    other_id = other_conversation.json()["id"]

    wrong_conversation = client.get(
        f"/api/v1/customer-service/conversations/{other_id}"
        f"/turns/{turn_id}/events",
        headers=AGENT,
    )
    assert wrong_conversation.status_code == 404
    assert wrong_conversation.json()["code"] == "CONVERSATION_TURN_NOT_FOUND"

    foreign_tenant = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{turn_id}/events",
        headers={**AGENT, "X-Business-Units": "bu_other"},
    )
    assert foreign_tenant.status_code == 403

    unauthorized_role = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}"
        f"/turns/{turn_id}/events",
        headers={"X-Actor-Id": "buyer", "X-Actor-Role": "requester"},
    )
    assert unauthorized_role.status_code == 403


def test_illegal_and_repeated_turn_transitions_are_rejected(
    client: TestClient,
) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        with pytest.raises(ApiProblem) as illegal:
            transition_turn(
                session,
                turn,
                TurnStatus.RUNNING,
                reason_code="TEST_ILLEGAL",
                actor_id="test",
            )
        assert illegal.value.status_code == 409
        assert illegal.value.code == "INVALID_TURN_TRANSITION"

        # Repeating the current status is a no-op, not a new event.
        assert (
            transition_turn(
                session,
                turn,
                TurnStatus.COMPLETED,
                reason_code="TEST_REPEAT",
                actor_id="test",
            )
            is False
        )
        with pytest.raises(ApiProblem) as stale:
            transition_turn(
                session,
                turn,
                TurnStatus.COMPLETED,
                reason_code="TEST_STALE",
                actor_id="test",
                expected_version=turn.version + 5,
            )
        assert stale.value.code == "CONVERSATION_TURN_VERSION_CONFLICT"
        session.rollback()

    assert len(_events(conversation_id, turn_id)) == 3


def test_duplicate_dispatch_of_finished_turn_is_idempotent(
    client: TestClient,
) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)
    before = _events(conversation_id, turn_id)

    process_conversation_turn(UUID(turn_id), "duplicate-dispatch")

    assert _events(conversation_id, turn_id) == before


def test_grounded_status_requires_supported_claims() -> None:
    citation = [{"chunk_id": "chunk-1"}]
    assert (
        grounding_status_from_claims(citations=[], claims=[]) == "NO_KNOWLEDGE"
    )
    assert (
        grounding_status_from_claims(
            citations=citation,
            claims=[
                {
                    "cited_chunk_ids": ["chunk-1"],
                    "verification_verdict": "not_checked",
                }
            ],
        )
        == "UNVERIFIED"
    )
    assert (
        grounding_status_from_claims(
            citations=citation,
            claims=[
                {
                    "cited_chunk_ids": ["chunk-1"],
                    "verification_verdict": "uncertain",
                }
            ],
        )
        == "UNSUPPORTED"
    )
    assert (
        grounding_status_from_claims(
            citations=citation,
            claims=[
                {
                    "cited_chunk_ids": ["chunk-1"],
                    "verification_verdict": "supported",
                }
            ],
        )
        == "GROUNDED"
    )
    assert (
        grounding_status_from_claims(
            citations=citation,
            claims=[{"cited_chunk_ids": [], "verification_verdict": "supported"}],
        )
        == "UNVERIFIED"
    )


def test_reclaim_reschedules_expired_turn(client: TestClient) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)
    _force_stuck_turn(turn_id)

    with SessionLocal() as session:
        reclaimed = reclaim_stuck_turns(session, limit=10)

    assert reclaimed == [UUID(turn_id)]
    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        assert turn.status == "PENDING"
        assert turn.attempt_count == 1
        assert turn.lease_expires_at is not None
        assert _as_aware(turn.lease_expires_at) > datetime.now(UTC)

    event_types = [event["event_type"] for event in _events(conversation_id, turn_id)]
    assert "TURN_RECLAIMED" in event_types
    assert "TURN_RETRY_SCHEDULED" in event_types

    # A live lease is left alone.
    with SessionLocal() as session:
        assert reclaim_stuck_turns(session, limit=10) == []


def test_reclaim_stops_at_max_attempts(client: TestClient) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)
    max_attempts = get_settings().conversation_turn_max_attempts
    _force_stuck_turn(turn_id, attempt_count=max_attempts)

    with SessionLocal() as session:
        assert reclaim_stuck_turns(session, limit=10) == []

    with SessionLocal() as session:
        turn = session.get(ConversationTurn, UUID(turn_id))
        assert turn is not None
        assert turn.status == "FAILED_TERMINAL"
    events = _events(conversation_id, turn_id)
    assert events[-1]["event_type"] == "TURN_RECLAIMED"
    assert (
        events[-1]["payload"]["reason_code"] == "TURN_LEASE_EXPIRED_MAX_ATTEMPTS"
    )


def test_operator_endpoint_reclaims_stuck_turn(client: TestClient) -> None:
    conversation_id, turn_id = _small_talk_conversation(client)
    _force_stuck_turn(turn_id, status="PENDING", attempt_count=0)

    response = client.post(
        "/api/v1/customer-service/turns/reclaim",
        headers=SUPERVISOR,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"reclaimed": 1, "redispatched": 1}
    event_types = [event["event_type"] for event in _events(conversation_id, turn_id)]
    # A PENDING turn never reached a worker, so it is rescheduled, not
    # reclaimed from a dead run.
    assert "TURN_RETRY_SCHEDULED" in event_types

    denied = client.post(
        "/api/v1/customer-service/turns/reclaim",
        headers=AGENT,
    )
    assert denied.status_code == 403
