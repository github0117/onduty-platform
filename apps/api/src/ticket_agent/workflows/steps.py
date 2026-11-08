"""Step handlers and the exception contract the executor understands.

Handlers receive a detached context (ids copied out before the short claim
transaction commits) and must be safe to call more than once with the same
context: a retried step is the normal path, not an accident.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ticket_agent.audit.service import record_audit
from ticket_agent.shared.db import system_session
from ticket_agent.tickets.models import AuditEvent, Ticket


class StepRetryableError(Exception):
    """The step can succeed on a later attempt (429, 5xx, timeout)."""


class StepNonRetryableError(Exception):
    """Retrying cannot help; move the step straight to a terminal failure."""


@dataclass(frozen=True)
class WorkflowContext:
    run_id: UUID
    step_id: UUID
    business_unit_id: str
    workflow_type: str
    step_name: str
    attempt: int
    context: dict[str, Any]


StepHandler = Callable[[WorkflowContext], dict[str, Any] | None]

STEP_HANDLERS: dict[tuple[str, str], StepHandler] = {}


def register_step(workflow_type: str, step_name: str) -> Callable[[StepHandler], StepHandler]:
    def decorator(handler: StepHandler) -> StepHandler:
        STEP_HANDLERS[(workflow_type, step_name)] = handler
        return handler

    return decorator


def get_step_handler(workflow_type: str, step_name: str) -> StepHandler:
    try:
        return STEP_HANDLERS[(workflow_type, step_name)]
    except KeyError:
        raise StepNonRetryableError(
            f"No handler registered for workflow '{workflow_type}' step '{step_name}'."
        ) from None


@register_step("ticket_sync", "sync_external")
def sync_external(context: WorkflowContext) -> dict[str, Any]:
    """Push the approved answer to the external ticket system.

    ``TicketSyncService`` already owns the external idempotency key
    (``ticket-sync:{ticket_id}:...``), so repeating this handler never creates
    a second remote ticket.
    """
    from ticket_agent.integrations.sync import TicketSyncService

    ticket_id = _uuid_context(context, "ticket_id", "WORKFLOW_CONTEXT_MISSING_TICKET_ID")
    correlation_id = str(context.context.get("correlation_id") or f"workflow:{context.run_id}")
    with system_session() as session:
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise StepNonRetryableError(f"TICKET_NOT_FOUND: {ticket_id} does not exist.")
        TicketSyncService(session).sync(ticket_id, correlation_id)
        return {"ticket_id": str(ticket_id), "sync_status": ticket.sync_status}


@register_step("ticket_sync", "notify")
def notify(context: WorkflowContext) -> dict[str, Any]:
    """Record an idempotent in-app notification for the requester.

    The audit row id is derived from the run and step, so a retried or
    replayed notify step finds the existing notification instead of writing a
    duplicate one. External delivery is deliberately out of scope: replies to
    a channel go through ``external_outbound_messages``, which has its own
    unique idempotency key.
    """
    ticket_id = _uuid_context(context, "ticket_id", "WORKFLOW_CONTEXT_MISSING_TICKET_ID")
    notification_key = f"workflow-notify:{context.run_id}:{context.step_name}"
    with system_session() as session:
        existing = session.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "workflow.notified",
                AuditEvent.correlation_id == notification_key,
            )
        )
        if existing is not None:
            return {"deduplicated": True, "notification_id": str(existing.id)}
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise StepNonRetryableError(f"TICKET_NOT_FOUND: {ticket_id} does not exist.")
        event = record_audit(
            session,
            correlation_id=notification_key,
            event_type="workflow.notified",
            actor_type="SYSTEM",
            actor_id="workflow-engine",
            resource_type="ticket",
            resource_id=ticket.id,
            action="notify",
            decision="EXECUTED",
            payload={
                "business_unit_id": ticket.business_unit_id,
                "requester_ref": ticket.requester_ref,
                "trigger": "ticket_sync",
                "recipient": ticket.requester_ref,
                "notification_key": notification_key,
            },
        )
        session.commit()
        return {"deduplicated": False, "notification_id": str(event.id)}


@register_step("ecommerce_publish", "publish")
def ecommerce_publish(context: WorkflowContext) -> dict[str, Any]:
    from ticket_agent.ecommerce.worker import publish_ecommerce_listing_job

    task_id = _uuid_context(context, "task_id", "WORKFLOW_CONTEXT_MISSING_TASK_ID")
    publish_ecommerce_listing_job(task_id, _correlation_id(context))
    return {"task_id": str(task_id)}


@register_step("knowledge_ingest", "ingest")
def knowledge_ingest(context: WorkflowContext) -> dict[str, Any]:
    from ticket_agent.knowledge.worker import ingest_knowledge_version_job

    version_id = _uuid_context(context, "version_id", "WORKFLOW_CONTEXT_MISSING_VERSION_ID")
    ingest_knowledge_version_job(version_id, _correlation_id(context))
    return {"version_id": str(version_id)}


def _uuid_context(context: WorkflowContext, key: str, error_code: str) -> UUID:
    raw = context.context.get(key)
    if not raw:
        raise StepNonRetryableError(f"{error_code}: workflow context has no '{key}'.")
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise StepNonRetryableError(f"{error_code}: '{raw}' is not a UUID.") from exc


def _correlation_id(context: WorkflowContext) -> str:
    return str(context.context.get("correlation_id") or f"workflow:{context.run_id}")
