from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ticket_agent.outbox import service as outbox_service
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.domain import TicketStatus, WorkflowState
from ticket_agent.tickets.models import OutboxEvent, Ticket


def _create_ticket_and_event() -> tuple[str, str]:
    with SessionLocal() as session:
        ticket = Ticket(
            business_unit_id="bu_demo",
            source_system="outbox_test",
            source_ticket_id=str(uuid4()),
            source_channel="test",
            idempotency_key=f"outbox:{uuid4()}",
            request_hash="a" * 64,
            requester_ref="customer_outbox",
            customer_tier="standard",
            subject="如何配置企业通知",
            body="请问管理员如何为团队配置消息通知？",
            status=TicketStatus.OPEN,
            workflow_state=WorkflowState.RECEIVED,
        )
        session.add(ticket)
        session.flush()
        event = OutboxEvent(
            aggregate_type="ticket",
            aggregate_id=ticket.id,
            event_type="ticket.received",
            payload_json={
                "ticket_id": str(ticket.id),
                "correlation_id": "outbox-test",
            },
        )
        session.add(event)
        session.commit()
        return str(event.id), str(ticket.id)


def test_outbox_retries_and_then_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    event_id, ticket_id = _create_ticket_and_event()

    def fail_dispatch(ticket_id: object, correlation_id: str) -> None:
        del ticket_id, correlation_id
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(outbox_service, "process_ticket_job", fail_dispatch)
    first = outbox_service.dispatch_outbox_event(UUID(event_id))

    assert first.dispatched is False
    with SessionLocal() as session:
        event = session.get(OutboxEvent, UUID(event_id))
        assert event is not None
        assert event.status == "PENDING"
        assert event.attempt_count == 1
        assert "broker unavailable" in (event.last_error or "")
        event.available_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    monkeypatch.undo()
    results = outbox_service.dispatch_pending_events()

    assert any(result.event_id == UUID(event_id) and result.dispatched for result in results)
    with SessionLocal() as session:
        event = session.get(OutboxEvent, UUID(event_id))
        ticket = session.get(Ticket, UUID(ticket_id))
        assert event is not None
        assert event.status == "SENT"
        assert ticket is not None
        assert ticket.workflow_state == WorkflowState.PENDING_REVIEW


def test_created_ticket_marks_outbox_event_sent(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tickets",
        json={
            "business_unit_id": "bu_demo",
            "source": {
                "system": "demo_helpdesk",
                "channel": "web_form",
                "external_ticket_id": "OUTBOX-API-001",
            },
            "requester": {
                "external_ref": "customer_outbox_api",
                "customer_tier": "standard",
            },
            "subject": "如何配置企业通知",
            "body": "请问管理员如何为团队配置消息通知？",
            "locale": "zh-CN",
            "attachments": [],
            "metadata": {},
        },
        headers={"Idempotency-Key": "source:OUTBOX-API-001"},
    )
    assert response.status_code == 202

    with SessionLocal() as session:
        event = session.scalar(select(OutboxEvent))
        assert event is not None
        assert event.status == "SENT"
        assert event.sent_at is not None

