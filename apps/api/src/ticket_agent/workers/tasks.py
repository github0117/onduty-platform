# mypy: disallow_untyped_decorators=False

from uuid import UUID

from celery import Task

from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.customer_service.worker import (
    auto_assign_customer_conversations_job,
)
from ticket_agent.ecommerce.adapters import EcommerceChannelError
from ticket_agent.ecommerce.worker import (
    fail_ecommerce_listing_job,
    generate_ecommerce_listing_batch_job,
    publish_ecommerce_listing_job,
    render_ecommerce_video_job,
)
from ticket_agent.integrations.worker import sync_ticket_job
from ticket_agent.knowledge.worker import ingest_knowledge_version_job
from ticket_agent.mcp_connectors.incidents import McpActionIncidentService
from ticket_agent.outbox.service import dispatch_pending_events
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import Ticket
from ticket_agent.workers.celery_app import celery_app
from ticket_agent.workers.process_ticket import process_ticket_job
from ticket_agent.workforce.worker import execute_workforce_task_job


@celery_app.task(
    name="ticket_agent.ticket.process",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_ticket_task(
    self: Task,
    ticket_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        process_ticket_job(UUID(ticket_id), correlation_id)
        with SessionLocal() as session:
            ticket = session.get(Ticket, UUID(ticket_id))
            if ticket is not None:
                auto_assign_customer_conversations_job(
                    ticket.business_unit_id
                )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1))) from exc


@celery_app.task(name="ticket_agent.outbox.dispatch_pending")
def dispatch_outbox_task() -> int:
    return sum(result.dispatched for result in dispatch_pending_events())


@celery_app.task(name="ticket_agent.customer_service.reclaim_offline")
def reclaim_offline_customer_agents_task() -> int:
    with SessionLocal() as session:
        return CustomerConversationService(session).reclaim_offline_conversations()


@celery_app.task(name="ticket_agent.customer_service.escalate_sla")
def escalate_customer_service_sla_task() -> int:
    with SessionLocal() as session:
        return CustomerConversationService(session).escalate_overdue_conversations()


@celery_app.task(name="ticket_agent.customer_service.notify_supervisors")
def notify_customer_service_supervisors_task() -> int:
    with SessionLocal() as session:
        return CustomerConversationService(session).sync_supervisor_notifications()


@celery_app.task(name="ticket_agent.customer_service.auto_assign")
def auto_assign_customer_conversations_task(
    business_unit_id: str | None = None,
) -> int:
    return auto_assign_customer_conversations_job(business_unit_id)


@celery_app.task(name="ticket_agent.mcp.reconcile_incidents")
def reconcile_mcp_incidents_task() -> int:
    settings = get_settings()
    with SessionLocal() as session:
        return McpActionIncidentService(session).reconcile_open_incidents(
            limit=settings.mcp_reconciliation_batch_size,
        )


@celery_app.task(name="ticket_agent.workforce.execute")
def execute_workforce_task(
    task_id: str,
    correlation_id: str,
) -> None:
    execute_workforce_task_job(UUID(task_id), correlation_id)


@celery_app.task(
    name="ticket_agent.knowledge.ingest",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ingest_knowledge_version_task(
    self: Task,
    version_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        ingest_knowledge_version_job(UUID(version_id), correlation_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1))) from exc


@celery_app.task(
    name="ticket_agent.ticket.sync",
    bind=True,
    max_retries=5,
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_ticket_task(
    self: Task,
    ticket_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        sync_ticket_job(UUID(ticket_id), correlation_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(60, 2 ** (self.request.retries + 1))) from exc


@celery_app.task(
    name="ticket_agent.ecommerce.listing.publish",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def publish_ecommerce_listing_task(
    self: Task,
    task_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        publish_ecommerce_listing_job(UUID(task_id), correlation_id)
    except EcommerceChannelError as exc:
        if exc.retryable and self.request.retries < 3:
            raise self.retry(
                exc=exc,
                countdown=min(30, 2 ** (self.request.retries + 1)),
            ) from exc
        fail_ecommerce_listing_job(UUID(task_id), exc)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(30, 2 ** (self.request.retries + 1))) from exc


@celery_app.task(
    name="ticket_agent.ecommerce.storyboard.video_render",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=True,
)
def render_ecommerce_storyboard_video_task(
    self: Task,
    job_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        render_ecommerce_video_job(UUID(job_id), correlation_id)
    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=min(30, 2 ** (self.request.retries + 1)),
        ) from exc


@celery_app.task(
    name="ticket_agent.ecommerce.listing.batch_generate",
    bind=True,
    max_retries=2,
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_ecommerce_listing_batch_task(
    self: Task,
    batch_job_id: str,
    correlation_id: str,
    outbox_event_id: str,
) -> None:
    del outbox_event_id
    try:
        generate_ecommerce_listing_batch_job(
            UUID(batch_job_id),
            correlation_id,
        )
    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=min(30, 2 ** (self.request.retries + 1)),
        ) from exc

