from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ticket_agent.tickets.models import AuditEvent


def record_audit(
    session: Session,
    *,
    correlation_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str,
    resource_id: UUID | str,
    action: str,
    decision: str,
    resource_type: str = "ticket",
    on_behalf_of: str | None = None,
    reason_code: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        correlation_id=correlation_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        on_behalf_of=on_behalf_of,
        resource_type=resource_type,
        resource_id=str(resource_id),
        action=action,
        decision=decision,
        reason_code=reason_code,
        redacted_payload=payload or {},
    )
    session.add(event)
    return event

