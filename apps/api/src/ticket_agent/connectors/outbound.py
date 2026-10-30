"""Outbound delivery for external connectors.

Every reply is first written to ``external_outbound_messages`` and an
outbox event in the same transaction. A crash between queueing and sending
therefore leaves a durable row the outbox can retry; a second queue attempt
with the same idempotency key returns the existing row instead of sending
twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.connectors.base import ConnectorError, OutboundEnvelope
from ticket_agent.connectors.factory import build_outbound_adapter
from ticket_agent.connectors.models import (
    ExternalConnector,
    ExternalInboundMessage,
    ExternalOutboundMessage,
)
from ticket_agent.customer_service.models import (
    CustomerConversation,
    CustomerMessage,
)
from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import OutboxEvent

OUTBOUND_DIRECTIONS = {"OUTBOUND", "BIDIRECTIONAL"}
REPLY_PREFIX = "Re: "


def enqueue_conversation_reply(
    session: Session,
    *,
    connector: ExternalConnector,
    conversation: CustomerConversation,
    content: str,
    idempotency_key: str,
    correlation_id: str,
    subject: str | None = None,
) -> ExternalOutboundMessage | None:
    if connector.direction not in OUTBOUND_DIRECTIONS:
        return None
    recipient = (conversation.requester_ref or "").strip()
    if not recipient:
        return None
    existing = session.scalar(
        select(ExternalOutboundMessage).where(
            ExternalOutboundMessage.connector_id == connector.id,
            ExternalOutboundMessage.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing
    outbound = ExternalOutboundMessage(
        connector_id=connector.id,
        business_unit_id=connector.business_unit_id,
        conversation_id=conversation.id,
        idempotency_key=idempotency_key,
        recipient=recipient[:320],
        subject=(subject or reply_subject(conversation.external_subject))[:500],
        content=content,
        status="QUEUED",
    )
    session.add(outbound)
    session.flush()
    event = OutboxEvent(
        aggregate_type="external_connector",
        aggregate_id=connector.id,
        event_type="connector.outbound.send",
        payload_json={
            "outbound_message_id": str(outbound.id),
            "correlation_id": correlation_id,
        },
    )
    session.add(event)
    session.flush()
    outbound.outbox_event_id = event.id
    record_audit(
        session,
        correlation_id=correlation_id,
        event_type="connector.outbound.queued",
        actor_type="SERVICE",
        actor_id=f"connector.{connector.connector_key}",
        resource_type="external_connector",
        resource_id=connector.id,
        action="send",
        decision="EXECUTED",
        payload={
            "outbound_message_id": str(outbound.id),
            "conversation_id": str(conversation.id),
            "content_length": len(content),
        },
    )
    return outbound


def reply_subject(original: str | None) -> str:
    subject = (original or "").strip()
    if not subject:
        return REPLY_PREFIX + "咨询回复"
    lowered = subject.lower()
    if lowered.startswith("re:") or lowered.startswith("回复"):
        return subject
    return REPLY_PREFIX + subject


def _last_inbound_message_id(session: Session, conversation_id: UUID) -> str | None:
    row = session.scalar(
        select(ExternalInboundMessage)
        .where(ExternalInboundMessage.conversation_id == conversation_id)
        .order_by(ExternalInboundMessage.created_at.desc())
        .limit(1)
    )
    return row.external_message_id if row is not None else None


def deliver_outbound_message(outbound_id: UUID) -> None:
    """Send one queued message.

    Retryable failures re-raise so the outbox schedules another attempt.
    Terminal failures are recorded on the row and swallowed: retrying a
    rejected recipient forever would only fill the outbox.
    """
    with SessionLocal() as session:
        outbound = session.scalar(
            select(ExternalOutboundMessage)
            .where(ExternalOutboundMessage.id == outbound_id)
            .with_for_update()
        )
        if outbound is None or outbound.status == "SENT":
            return
        connector = session.get(ExternalConnector, outbound.connector_id)
        conversation = (
            session.get(CustomerConversation, outbound.conversation_id)
            if outbound.conversation_id is not None
            else None
        )
        if connector is None:
            outbound.status = "FAILED"
            outbound.last_error = "CONNECTOR_NOT_FOUND"
            session.commit()
            return
        outbound.attempt_count += 1
        if connector.status != "ACTIVE":
            outbound.status = "FAILED"
            outbound.last_error = "CONNECTOR_DISABLED"
            session.commit()
            return
        message_id = f"<external-outbound.{outbound.id}@connector.local>"
        envelope = OutboundEnvelope(
            recipient=outbound.recipient,
            subject=outbound.subject,
            content=outbound.content,
            message_id=message_id,
            in_reply_to=(
                _last_inbound_message_id(session, conversation.id)
                if conversation is not None
                else None
            ),
            thread_id=(
                conversation.external_thread_id
                if conversation is not None
                else None
            ),
        )
        try:
            adapter = build_outbound_adapter(connector)
            receipt = adapter.send(envelope)
        except ConnectorError as exc:
            outbound.last_error = f"{exc.code}: {exc.message}"[:2000]
            if exc.retryable:
                outbound.status = "QUEUED"
                session.commit()
                raise
            outbound.status = "FAILED"
            session.commit()
            record_audit(
                session,
                correlation_id=f"connector-outbound-{outbound.id}",
                event_type="connector.outbound.failed",
                actor_type="SERVICE",
                actor_id=f"connector.{connector.connector_key}",
                resource_type="external_connector",
                resource_id=connector.id,
                action="send",
                decision="DENIED",
                reason_code=exc.code,
                payload={"outbound_message_id": str(outbound.id)},
            )
            session.commit()
            return
        outbound.status = "SENT"
        outbound.sent_at = datetime.now(UTC)
        outbound.external_message_id = receipt.external_message_id[:256]
        outbound.last_error = None
        session.commit()
        record_audit(
            session,
            correlation_id=f"connector-outbound-{outbound.id}",
            event_type="connector.outbound.sent",
            actor_type="SERVICE",
            actor_id=f"connector.{connector.connector_key}",
            resource_type="external_connector",
            resource_id=connector.id,
            action="send",
            decision="EXECUTED",
            payload={"outbound_message_id": str(outbound.id)},
        )
        session.commit()


def last_assistant_message(
    session: Session,
    conversation_id: UUID,
) -> CustomerMessage | None:
    return session.scalar(
        select(CustomerMessage)
        .where(
            CustomerMessage.conversation_id == conversation_id,
            CustomerMessage.role == "ASSISTANT",
        )
        .order_by(CustomerMessage.sequence.desc())
        .limit(1)
    )
