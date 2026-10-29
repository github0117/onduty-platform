"""Inbound pipeline: dedupe, thread mapping, ticket/turn, auto reply."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.connectors.base import ConnectorError, InboundEnvelope
from ticket_agent.connectors.factory import build_inbound_adapter
from ticket_agent.connectors.models import (
    ExternalConnector,
    ExternalConnectorBinding,
    ExternalInboundMessage,
)
from ticket_agent.connectors.outbound import (
    enqueue_conversation_reply,
    last_assistant_message,
)
from ticket_agent.customer_service.models import (
    ConversationTurn,
    CustomerConversation,
)
from ticket_agent.customer_service.schemas import CustomerMessageCreate
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.turns import process_conversation_turn
from ticket_agent.identity.models import Principal
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.domain import WorkflowState
from ticket_agent.tickets.models import Ticket

logger = structlog.get_logger(__name__)

INBOUND_DIRECTIONS = {"INBOUND", "BIDIRECTIONAL"}
FINAL_STATUSES = {"PROCESSED", "FAILED", "SKIPPED"}


def _insert_or_get(
    session: Session,
    connector: ExternalConnector,
    envelope: InboundEnvelope,
    *,
    status: str = "RECEIVED",
    error_code: str | None = None,
    error_message: str | None = None,
) -> tuple[ExternalInboundMessage, bool]:
    existing = session.scalar(
        select(ExternalInboundMessage).where(
            ExternalInboundMessage.connector_id == connector.id,
            ExternalInboundMessage.external_message_id
            == envelope.external_message_id,
        )
    )
    if existing is not None:
        return existing, False
    row = ExternalInboundMessage(
        connector_id=connector.id,
        business_unit_id=connector.business_unit_id,
        external_message_id=envelope.external_message_id,
        external_conversation_id=envelope.external_conversation_id,
        external_user_id=envelope.external_user_id,
        subject=envelope.subject,
        content=envelope.content,
        raw_json=envelope.raw,
        status=status,
        error_code=error_code,
        error_message=error_message,
        processed_at=datetime.now(UTC) if status == "FAILED" else None,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ExternalInboundMessage).where(
                ExternalInboundMessage.connector_id == connector.id,
                ExternalInboundMessage.external_message_id
                == envelope.external_message_id,
            )
        )
        if existing is None:
            raise
        return existing, False
    session.refresh(row)
    return row, True


def ingest_envelope(
    connector_id: UUID,
    envelope: InboundEnvelope,
    *,
    correlation_id: str,
) -> tuple[ExternalInboundMessage, bool]:
    """Persist an inbound message, or return the row already stored.

    Validation failures are recorded as FAILED rows before the ApiProblem is
    raised, so an unbound or disabled connector leaves an auditable trace
    instead of silently dropping the message.
    """
    with SessionLocal() as session:
        connector = session.get(ExternalConnector, connector_id)
        if connector is None:
            raise ApiProblem(
                status_code=404,
                code="CONNECTOR_NOT_FOUND",
                title="Connector not found",
                detail=f"Connector {connector_id} does not exist.",
            )
        if connector.status != "ACTIVE":
            _insert_or_get(
                session,
                connector,
                envelope,
                status="FAILED",
                error_code="CONNECTOR_DISABLED",
                error_message="Connector is disabled.",
            )
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_DISABLED",
                title="Connector is disabled",
                detail="Inbound messages are rejected while the connector is disabled.",
            )
        if connector.direction not in INBOUND_DIRECTIONS:
            _insert_or_get(
                session,
                connector,
                envelope,
                status="FAILED",
                error_code="CONNECTOR_NOT_INBOUND",
                error_message="Connector direction does not accept inbound messages.",
            )
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_NOT_INBOUND",
                title="Connector does not accept inbound messages",
                detail="Change the connector direction before sending inbound traffic.",
            )
        if _binding(session, connector.id) is None:
            _insert_or_get(
                session,
                connector,
                envelope,
                status="FAILED",
                error_code="CONNECTOR_NOT_BOUND",
                error_message="Connector is not bound to a business service entry.",
            )
            raise ApiProblem(
                status_code=422,
                code="CONNECTOR_NOT_BOUND",
                title="Connector is not bound",
                detail="Bind the connector to a business service entry before receiving messages.",
            )
        row, created = _insert_or_get(session, connector, envelope)
        if created:
            record_audit(
                session,
                correlation_id=correlation_id,
                event_type="connector.inbound.received",
                actor_type="SERVICE",
                actor_id=f"connector.{connector.connector_key}",
                resource_type="external_connector",
                resource_id=connector.id,
                action="receive",
                decision="EXECUTED",
                payload={
                    "inbound_message_id": str(row.id),
                    "external_message_id": row.external_message_id,
                },
            )
            session.commit()
        session.refresh(row)
        return row, created


def _binding(
    session: Session,
    connector_id: UUID,
) -> ExternalConnectorBinding | None:
    return session.scalar(
        select(ExternalConnectorBinding)
        .where(ExternalConnectorBinding.connector_id == connector_id)
        .order_by(ExternalConnectorBinding.created_at)
        .limit(1)
    )


def _conversation_for_thread(
    session: Session,
    connector: ExternalConnector,
    row: ExternalInboundMessage,
) -> CustomerConversation:
    conversation = session.scalar(
        select(CustomerConversation)
        .where(
            CustomerConversation.external_connector_id == connector.id,
            CustomerConversation.external_thread_id
            == row.external_conversation_id,
        )
        .with_for_update()
    )
    if conversation is not None:
        return conversation
    binding = _binding(session, connector.id)
    conversation = CustomerConversation(
        business_unit_id=connector.business_unit_id,
        service_entry_id=binding.service_entry_id if binding else None,
        employee_id=binding.employee_id if binding else None,
        requester_ref=row.external_user_id[:128],
        channel=f"enterprise_{connector.connector_type}"[:64],
        status="ACTIVE",
        external_connector_id=connector.id,
        external_thread_id=row.external_conversation_id,
        external_subject=row.subject,
    )
    session.add(conversation)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(CustomerConversation).where(
                CustomerConversation.external_connector_id == connector.id,
                CustomerConversation.external_thread_id
                == row.external_conversation_id,
            )
        )
        if existing is None:
            raise
        return existing
    return conversation


def _service_principal(
    connector: ExternalConnector,
    external_user_id: str,
) -> Principal:
    return Principal(
        actor_id=f"connector.{connector.connector_key}",
        role="requester",
        service_identity="external_connector.v1",
        customer_ref=external_user_id,
        business_units=(connector.business_unit_id,),
    )


def process_inbound_record(inbound_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage)
            .where(ExternalInboundMessage.id == inbound_id)
            .with_for_update()
        )
        if row is None or row.status in {"PROCESSED", "PROCESSING"}:
            return
        if row.status == "FAILED" and row.error_code in {
            "CONNECTOR_DISABLED",
            "CONNECTOR_NOT_BOUND",
            "CONNECTOR_NOT_INBOUND",
        }:
            return
        connector = session.get(ExternalConnector, row.connector_id)
        if connector is None or connector.status != "ACTIVE":
            row.status = "FAILED"
            row.error_code = "CONNECTOR_DISABLED"
            row.error_message = "Connector is unavailable."
            row.processed_at = datetime.now(UTC)
            session.commit()
            return
        row.status = "PROCESSING"
        row.attempt_count += 1
        row.error_code = None
        row.error_message = None
        session.commit()

        try:
            conversation, turn_id = _open_conversation_turn(
                session,
                connector,
                row,
                correlation_id=correlation_id,
            )
        except ApiProblem as exc:
            session.rollback()
            _mark_failed(inbound_id, exc.code, exc.detail)
            return
        except Exception as exc:  # noqa: BLE001 - persisted on the row
            session.rollback()
            _mark_failed(
                inbound_id,
                "INBOUND_PROCESSING_FAILED",
                f"{type(exc).__name__}: {exc}",
            )
            return

    if turn_id is not None:
        try:
            process_conversation_turn(turn_id, correlation_id)
        except Exception as exc:  # noqa: BLE001
            _mark_failed(
                inbound_id,
                "TURN_PROCESSING_FAILED",
                f"{type(exc).__name__}: {exc}",
            )
            return

    _maybe_send_auto_reply(inbound_id, correlation_id=correlation_id)
    _mark_processed(inbound_id, conversation.id, correlation_id)


def _open_conversation_turn(
    session: Session,
    connector: ExternalConnector,
    row: ExternalInboundMessage,
    *,
    correlation_id: str,
) -> tuple[CustomerConversation, UUID | None]:
    conversation = _conversation_for_thread(session, connector, row)
    result = CustomerConversationService(session).append_buyer_message(
        conversation.id,
        CustomerMessageCreate(
            content=row.content,
            # Keyed by the inbound record: replaying an already-processed
            # inbound message must not open a second turn.
            client_message_id=f"connector-inbound:{row.id}",
        ),
        principal=_service_principal(connector, row.external_user_id),
        correlation_id=correlation_id,
    )
    updated, turn_id = result.conversation, result.turn_id
    row.conversation_id = updated.id
    row.ticket_id = updated.current_ticket_id
    row.turn_id = turn_id
    session.commit()
    return updated, turn_id


def _mark_processed(
    inbound_id: UUID,
    conversation_id: UUID,
    correlation_id: str,
) -> None:
    with SessionLocal() as session:
        row = session.get(ExternalInboundMessage, inbound_id)
        if row is None:
            return
        row.conversation_id = conversation_id
        row.status = "PROCESSED"
        row.processed_at = datetime.now(UTC)
        session.commit()
        record_audit(
            session,
            correlation_id=correlation_id,
            event_type="connector.inbound.processed",
            actor_type="SERVICE",
            actor_id="connector.runtime",
            resource_type="external_connector",
            resource_id=row.connector_id,
            action="process",
            decision="EXECUTED",
            payload={
                "inbound_message_id": str(row.id),
                "conversation_id": str(conversation_id),
            },
        )
        session.commit()


def _mark_failed(
    inbound_id: UUID,
    code: str,
    message: str,
) -> None:
    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage)
            .where(ExternalInboundMessage.id == inbound_id)
            .with_for_update()
        )
        if row is None:
            return
        row.status = "FAILED"
        row.error_code = code[:128]
        row.error_message = (message or "")[:2000]
        row.processed_at = datetime.now(UTC)
        session.commit()
        record_audit(
            session,
            correlation_id=f"connector-inbound-{inbound_id}",
            event_type="connector.inbound.failed",
            actor_type="SERVICE",
            actor_id="connector.runtime",
            resource_type="external_connector",
            resource_id=row.connector_id,
            action="process",
            decision="DENIED",
            reason_code=code,
            payload={"inbound_message_id": str(row.id)},
        )
        session.commit()


def _maybe_send_auto_reply(inbound_id: UUID, *, correlation_id: str) -> None:
    settings = get_settings()
    if not settings.connector_auto_reply_enabled:
        return
    with SessionLocal() as session:
        row = session.get(ExternalInboundMessage, inbound_id)
        if row is None or row.conversation_id is None:
            return
        connector = session.get(ExternalConnector, row.connector_id)
        conversation = session.get(CustomerConversation, row.conversation_id)
        if connector is None or conversation is None:
            return
        if not connector.auto_reply_enabled:
            return
        turn = session.scalar(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation.id)
            .order_by(ConversationTurn.sequence.desc())
            .limit(1)
        )
        if turn is not None:
            if turn.status != "COMPLETED":
                return
            # Unattended sending requires the accuracy gate to have cleared the
            # answer. A turn with no gate (legacy row or evaluation failure)
            # fails closed: a human sends it.
            gate = turn.gate_json or {}
            if gate.get("decision") != "AUTO_SEND":
                return
            ticket = (
                session.get(Ticket, turn.ticket_id)
                if turn.ticket_id is not None
                else None
            )
            if ticket is not None and ticket.workflow_state != WorkflowState.COMPLETED:
                return
        message = last_assistant_message(session, conversation.id)
        if message is None:
            return
        enqueue_conversation_reply(
            session,
            connector=connector,
            conversation=conversation,
            content=message.content,
            idempotency_key=f"inbound:{row.id}",
            correlation_id=correlation_id,
        )
        session.commit()


def retry_inbound(
    inbound_id: UUID,
    *,
    connector_id: UUID,
) -> ExternalInboundMessage:
    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalInboundMessage)
            .where(ExternalInboundMessage.id == inbound_id)
            .with_for_update()
        )
        if row is None or row.connector_id != connector_id:
            raise ApiProblem(
                status_code=404,
                code="INBOUND_MESSAGE_NOT_FOUND",
                title="Inbound message not found",
                detail=f"Inbound message {inbound_id} does not exist.",
            )
        if row.status == "PROCESSED":
            return row
        row.status = "RECEIVED"
        row.error_code = None
        row.error_message = None
        row.processed_at = None
        session.commit()
    process_inbound_record(inbound_id, f"connector-inbound-retry-{inbound_id}")
    with SessionLocal() as session:
        row = session.get(ExternalInboundMessage, inbound_id)
        if row is None:
            raise ApiProblem(
                status_code=404,
                code="INBOUND_MESSAGE_NOT_FOUND",
                title="Inbound message not found",
                detail=f"Inbound message {inbound_id} does not exist.",
            )
        return row


def poll_correlation_id(connector_id: UUID, external_message_id: str) -> str:
    """Stable trace id that always fits ``audit_events.correlation_id``."""
    digest = hashlib.sha256(
        f"{connector_id}:{external_message_id}".encode()
    ).hexdigest()[:32]
    return f"connector-poll-{digest}"


def poll_connector(connector_id: UUID) -> int:
    with SessionLocal() as session:
        connector = session.get(ExternalConnector, connector_id)
        if connector is None or connector.status != "ACTIVE":
            return 0
        adapter = build_inbound_adapter(connector)
    limit = get_settings().connector_poll_batch_size
    fetched = adapter.fetch_inbound(limit=limit)
    processed = 0
    for item in fetched:
        correlation_id = poll_correlation_id(
            connector_id,
            item.envelope.external_message_id,
        )
        try:
            row, created = ingest_envelope(
                connector_id,
                item.envelope,
                correlation_id=correlation_id,
            )
        except ApiProblem:
            _acknowledge(adapter, item.ack_token)
            continue
        if created:
            process_inbound_record(row.id, correlation_id)
            processed += 1
        _acknowledge(adapter, item.ack_token)
    return processed


def _acknowledge(adapter: object, token: str) -> None:
    acknowledge = getattr(adapter, "acknowledge", None)
    if acknowledge is None:
        return
    try:
        acknowledge(token)
    except Exception as exc:  # noqa: BLE001 - a stale flag is retried next poll
        logger.warning(
            "connector.acknowledge_failed",
            error=f"{type(exc).__name__}: {exc}",
        )


def poll_email_connectors_job() -> int:
    with SessionLocal() as session:
        connector_ids = list(
            session.scalars(
                select(ExternalConnector.id).where(
                    ExternalConnector.connector_type == "email",
                    ExternalConnector.status == "ACTIVE",
                    ExternalConnector.direction.in_(
                        ["INBOUND", "BIDIRECTIONAL"]
                    ),
                )
            ).all()
        )
    total = 0
    for connector_id in connector_ids:
        try:
            total += poll_connector(connector_id)
        except ConnectorError as exc:
            logger.warning(
                "connector.poll_failed",
                connector_id=str(connector_id),
                code=exc.code,
                retryable=exc.retryable,
            )
        except Exception as exc:  # noqa: BLE001 - one mailbox must not stop the rest
            logger.warning(
                "connector.poll_failed",
                connector_id=str(connector_id),
                error=f"{type(exc).__name__}: {exc}",
            )
    return total
