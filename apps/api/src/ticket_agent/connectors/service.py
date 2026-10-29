"""Connector registry, bindings, health and read-only queries."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.business_entries.models import BusinessServiceEntry
from ticket_agent.connectors.base import (
    ConnectorError,
    has_secret,
    resolve_secret,
)
from ticket_agent.connectors.email_adapter import EmailConnectorAdapter
from ticket_agent.connectors.http_json_adapter import HTTPJSONReadAdapter
from ticket_agent.connectors.models import (
    ExternalConnector,
    ExternalConnectorBinding,
    ExternalInboundMessage,
    ExternalOutboundMessage,
)
from ticket_agent.connectors.schemas import (
    ConnectorBindingInput,
    ConnectorBindingView,
    ConnectorCreate,
    ConnectorHealthView,
    ConnectorInboundView,
    ConnectorOutboundView,
    ConnectorQueryView,
    ConnectorUpdate,
    ConnectorView,
    _reject_credentials,
    _validate_email,
    _validate_http,
)
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem


def _not_found(connector_id: UUID) -> ApiProblem:
    return ApiProblem(
        status_code=404,
        code="CONNECTOR_NOT_FOUND",
        title="Connector not found",
        detail=f"Connector {connector_id} does not exist.",
    )


def _adapter_failure(exc: ConnectorError) -> ApiProblem:
    return ApiProblem(
        status_code=503 if exc.retryable else 409,
        code=exc.code,
        title="Connector operation failed",
        detail=exc.message,
        retryable=exc.retryable,
    )


class ExternalConnectorService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, connector_id: UUID) -> ExternalConnector:
        connector = self.session.get(ExternalConnector, connector_id)
        if connector is None:
            raise _not_found(connector_id)
        return connector

    def list_connectors(
        self,
        business_unit_id: str,
        *,
        status: str | None = None,
    ) -> list[ExternalConnector]:
        statement = select(ExternalConnector).where(
            ExternalConnector.business_unit_id == business_unit_id
        )
        if status:
            statement = statement.where(ExternalConnector.status == status)
        return list(
            self.session.scalars(
                statement.order_by(ExternalConnector.created_at.desc())
            ).all()
        )

    def view(self, connector: ExternalConnector) -> ConnectorView:
        return ConnectorView(
            id=connector.id,
            business_unit_id=connector.business_unit_id,
            connector_key=connector.connector_key,
            name=connector.name,
            connector_type=connector.connector_type,
            direction=connector.direction,
            status=connector.status,
            config=connector.config_json,
            field_mapping=connector.field_mapping_json,
            secret_ref=connector.secret_ref,
            secret_configured=has_secret(connector.secret_ref),
            auto_reply_enabled=connector.auto_reply_enabled,
            version=connector.version,
            last_health_status=connector.last_health_status,
            last_health_at=connector.last_health_at,
            last_health_error=connector.last_health_error,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    def create(
        self,
        payload: ConnectorCreate,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> ExternalConnector:
        duplicate = self.session.scalar(
            select(ExternalConnector).where(
                ExternalConnector.business_unit_id == payload.business_unit_id,
                ExternalConnector.connector_key == payload.connector_key,
            )
        )
        if duplicate is not None:
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_KEY_EXISTS",
                title="Connector key already exists",
                detail="connector_key must be unique inside a business unit.",
            )
        connector = ExternalConnector(
            business_unit_id=payload.business_unit_id,
            connector_key=payload.connector_key,
            name=payload.name,
            connector_type=payload.connector_type,
            direction=payload.direction,
            status=payload.status,
            config_json=payload.config,
            field_mapping_json=payload.field_mapping,
            secret_ref=payload.secret_ref,
            auto_reply_enabled=payload.auto_reply_enabled,
        )
        self.session.add(connector)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_KEY_EXISTS",
                title="Connector key already exists",
                detail="connector_key must be unique inside a business unit.",
            ) from exc
        self.session.refresh(connector)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="connector.created",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="external_connector",
            resource_id=connector.id,
            action="create",
            decision="EXECUTED",
            payload={
                "connector_key": connector.connector_key,
                "connector_type": connector.connector_type,
                "direction": connector.direction,
            },
        )
        self.session.commit()
        return connector

    def update(
        self,
        connector_id: UUID,
        payload: ConnectorUpdate,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> ExternalConnector:
        connector = self.get(connector_id)
        if (
            payload.expected_version is not None
            and payload.expected_version != connector.version
        ):
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_VERSION_CONFLICT",
                title="Connector was modified",
                detail="Reload the connector before applying this change.",
            )
        direction = payload.direction or connector.direction
        config = dict(connector.config_json)
        if payload.config is not None:
            config.update(payload.config)
        field_mapping = dict(connector.field_mapping_json)
        if payload.field_mapping is not None:
            field_mapping.update(payload.field_mapping)
        try:
            _reject_credentials(config, field_mapping)
            if connector.connector_type == "email":
                _validate_email(config, direction)
            else:
                _validate_http(config, direction)
        except ValueError as exc:
            raise ApiProblem(
                status_code=422,
                code="CONNECTOR_CONFIG_INVALID",
                title="Connector config is invalid",
                detail=str(exc),
            ) from exc

        if payload.name is not None:
            connector.name = payload.name
        connector.direction = direction
        connector.config_json = config
        connector.field_mapping_json = field_mapping
        if payload.secret_ref is not None:
            connector.secret_ref = payload.secret_ref or None
        if payload.auto_reply_enabled is not None:
            connector.auto_reply_enabled = payload.auto_reply_enabled
        if payload.status is not None:
            connector.status = payload.status
        connector.version += 1
        self.session.commit()
        self.session.refresh(connector)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="connector.updated",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="external_connector",
            resource_id=connector.id,
            action="update",
            decision="EXECUTED",
            payload={
                "connector_key": connector.connector_key,
                "status": connector.status,
                "direction": connector.direction,
            },
        )
        self.session.commit()
        return connector

    # ----- bindings -------------------------------------------------

    def binding_views(self, connector_id: UUID) -> list[ConnectorBindingView]:
        bindings = list(
            self.session.scalars(
                select(ExternalConnectorBinding)
                .where(ExternalConnectorBinding.connector_id == connector_id)
                .order_by(ExternalConnectorBinding.created_at)
            ).all()
        )
        views: list[ConnectorBindingView] = []
        for binding in bindings:
            entry = (
                self.session.get(BusinessServiceEntry, binding.service_entry_id)
                if binding.service_entry_id is not None
                else None
            )
            employee = (
                self.session.get(DigitalEmployee, binding.employee_id)
                if binding.employee_id is not None
                else None
            )
            views.append(
                ConnectorBindingView(
                    id=binding.id,
                    connector_id=binding.connector_id,
                    service_entry_id=binding.service_entry_id,
                    service_entry_name=entry.name if entry else None,
                    employee_id=binding.employee_id,
                    employee_name=employee.name if employee else None,
                    allowed_operations=list(
                        binding.allowed_operations_json or []
                    ),
                    write_approved=binding.write_approved,
                )
            )
        return views

    def replace_bindings(
        self,
        connector_id: UUID,
        bindings_payload: list[ConnectorBindingInput],
        *,
        actor_id: str,
        correlation_id: str,
    ) -> list[ConnectorBindingView]:
        connector = self.get(connector_id)
        seen: set[UUID] = set()
        for item in bindings_payload:
            if item.service_entry_id in seen:
                raise ApiProblem(
                    status_code=422,
                    code="CONNECTOR_BINDING_DUPLICATE",
                    title="Duplicate binding",
                    detail="Each business service entry can be bound only once.",
                )
            seen.add(item.service_entry_id)
            entry = self.session.get(
                BusinessServiceEntry,
                item.service_entry_id,
            )
            if entry is None:
                raise ApiProblem(
                    status_code=422,
                    code="CONNECTOR_BINDING_ENTRY_NOT_FOUND",
                    title="Business service entry not found",
                    detail=f"Entry {item.service_entry_id} does not exist.",
                )
            if entry.business_unit_id != connector.business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="CONNECTOR_BINDING_SCOPE_MISMATCH",
                    title="Binding scope mismatch",
                    detail="The entry belongs to another business unit.",
                )
            if item.employee_id is not None:
                employee = self.session.get(DigitalEmployee, item.employee_id)
                if (
                    employee is None
                    or employee.business_unit_id != connector.business_unit_id
                ):
                    raise ApiProblem(
                        status_code=422,
                        code="CONNECTOR_BINDING_EMPLOYEE_INVALID",
                        title="Binding employee is invalid",
                        detail="The employee must exist in the same business unit.",
                    )
        existing = list(
            self.session.scalars(
                select(ExternalConnectorBinding).where(
                    ExternalConnectorBinding.connector_id == connector.id
                )
            ).all()
        )
        for binding in existing:
            self.session.delete(binding)
        self.session.flush()
        for item in bindings_payload:
            self.session.add(
                ExternalConnectorBinding(
                    connector_id=connector.id,
                    business_unit_id=connector.business_unit_id,
                    service_entry_id=item.service_entry_id,
                    employee_id=item.employee_id,
                    allowed_operations_json=item.allowed_operations,
                    write_approved=item.write_approved,
                )
            )
        self.session.commit()
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="connector.bindings.replaced",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="external_connector",
            resource_id=connector.id,
            action="bind",
            decision="EXECUTED",
            payload={"binding_count": len(bindings_payload)},
        )
        self.session.commit()
        return self.binding_views(connector.id)

    # ----- health / query ------------------------------------------

    def health(self, connector_id: UUID) -> ConnectorHealthView:
        connector = self.get(connector_id)
        adapter: Any
        if connector.connector_type == "email":
            adapter = EmailConnectorAdapter(connector)
        else:
            adapter = HTTPJSONReadAdapter(connector)
        checked_at = datetime.now(UTC)
        try:
            result = adapter.health()
        except ConnectorError as exc:
            connector.last_health_status = "UNHEALTHY"
            connector.last_health_at = checked_at
            connector.last_health_error = f"{exc.code}: {exc.message}"[:2000]
            self.session.commit()
            return ConnectorHealthView(
                connector_id=connector.id,
                healthy=False,
                detail=exc.message,
                metadata={"code": exc.code, "retryable": exc.retryable},
                checked_at=checked_at,
            )
        except Exception as exc:  # noqa: BLE001 - reported as health detail
            connector.last_health_status = "UNHEALTHY"
            connector.last_health_at = checked_at
            connector.last_health_error = f"{type(exc).__name__}: {exc}"[:2000]
            self.session.commit()
            return ConnectorHealthView(
                connector_id=connector.id,
                healthy=False,
                detail=f"{type(exc).__name__}: {exc}",
                metadata={"code": "CONNECTOR_HEALTH_FAILED"},
                checked_at=checked_at,
            )
        connector.last_health_status = "HEALTHY"
        connector.last_health_at = checked_at
        connector.last_health_error = None
        self.session.commit()
        return ConnectorHealthView(
            connector_id=connector.id,
            healthy=True,
            detail=result.detail,
            metadata=result.metadata,
            checked_at=checked_at,
        )

    def query(
        self,
        connector_id: UUID,
        params: dict[str, str],
    ) -> ConnectorQueryView:
        connector = self.get(connector_id)
        if connector.status != "ACTIVE":
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_DISABLED",
                title="Connector is disabled",
                detail="Enable the connector before querying it.",
            )
        if connector.connector_type != "http_json":
            raise ApiProblem(
                status_code=409,
                code="CONNECTOR_QUERY_UNSUPPORTED",
                title="Connector does not support queries",
                detail="Only http_json connectors expose read-only queries here.",
            )
        try:
            result = HTTPJSONReadAdapter(connector).query(params)
        except ConnectorError as exc:
            raise _adapter_failure(exc) from exc
        return ConnectorQueryView(
            connector_id=connector.id,
            status_code=int(result.get("status_code", 200)),
            data=result.get("data"),
        )

    # ----- message ledger ------------------------------------------

    def inbound_views(
        self,
        connector_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ConnectorInboundView]:
        rows = self.session.scalars(
            select(ExternalInboundMessage)
            .where(ExternalInboundMessage.connector_id == connector_id)
            .order_by(ExternalInboundMessage.created_at.desc())
            .limit(limit)
        ).all()
        return [inbound_view(row) for row in rows]

    def outbound_views(
        self,
        connector_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ConnectorOutboundView]:
        rows = self.session.scalars(
            select(ExternalOutboundMessage)
            .where(ExternalOutboundMessage.connector_id == connector_id)
            .order_by(ExternalOutboundMessage.created_at.desc())
            .limit(limit)
        ).all()
        return [outbound_view(row) for row in rows]


def inbound_view(row: ExternalInboundMessage) -> ConnectorInboundView:
    return ConnectorInboundView(
        id=row.id,
        connector_id=row.connector_id,
        external_message_id=row.external_message_id,
        external_conversation_id=row.external_conversation_id,
        external_user_id=row.external_user_id,
        subject=row.subject,
        status=row.status,
        attempt_count=row.attempt_count,
        conversation_id=row.conversation_id,
        ticket_id=row.ticket_id,
        turn_id=row.turn_id,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


def outbound_view(row: ExternalOutboundMessage) -> ConnectorOutboundView:
    return ConnectorOutboundView(
        id=row.id,
        connector_id=row.connector_id,
        conversation_id=row.conversation_id,
        recipient=row.recipient,
        subject=row.subject,
        status=row.status,
        attempt_count=row.attempt_count,
        external_message_id=row.external_message_id,
        last_error=row.last_error,
        created_at=row.created_at,
        sent_at=row.sent_at,
    )


def compute_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    connector: ExternalConnector,
    *,
    body: bytes,
    signature: str | None,
) -> None:
    if not signature:
        raise ApiProblem(
            status_code=401,
            code="CONNECTOR_SIGNATURE_MISSING",
            title="Missing connector signature",
            detail="Inbound webhooks require X-Connector-Signature.",
        )
    try:
        secret = resolve_secret(connector.secret_ref)
    except ConnectorError as exc:
        raise ApiProblem(
            status_code=503,
            code="CONNECTOR_SIGNATURE_SECRET_MISSING",
            title="Connector signature secret is not configured",
            detail=str(exc),
        ) from exc
    expected = compute_signature(secret, body)
    if not hmac.compare_digest(expected, signature.strip()):
        raise ApiProblem(
            status_code=401,
            code="CONNECTOR_SIGNATURE_INVALID",
            title="Invalid connector signature",
            detail="The signature does not match the raw request body.",
        )


def retry_outbound(
    outbound_id: UUID,
    *,
    connector_id: UUID,
) -> ExternalOutboundMessage:
    from ticket_agent.connectors.outbound import deliver_outbound_message

    with SessionLocal() as session:
        row = session.scalar(
            select(ExternalOutboundMessage)
            .where(ExternalOutboundMessage.id == outbound_id)
            .with_for_update()
        )
        if row is None or row.connector_id != connector_id:
            raise ApiProblem(
                status_code=404,
                code="OUTBOUND_MESSAGE_NOT_FOUND",
                title="Outbound message not found",
                detail=f"Outbound message {outbound_id} does not exist.",
            )
        if row.status == "SENT":
            return row
        row.status = "QUEUED"
        row.last_error = None
        session.commit()
    # A retryable failure is already persisted on the row; the outbox keeps
    # its own retry schedule for events it owns.
    with contextlib.suppress(ConnectorError):
        deliver_outbound_message(outbound_id)
    with SessionLocal() as session:
        row = session.get(ExternalOutboundMessage, outbound_id)
        if row is None:
            raise ApiProblem(
                status_code=404,
                code="OUTBOUND_MESSAGE_NOT_FOUND",
                title="Outbound message not found",
                detail=f"Outbound message {outbound_id} does not exist.",
            )
        return row
