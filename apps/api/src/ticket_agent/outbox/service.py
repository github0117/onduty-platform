from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import OutboxEvent
from ticket_agent.workers.process_ticket import process_ticket_job


@dataclass(frozen=True)
class DispatchResult:
    event_id: UUID
    dispatched: bool
    error: str | None = None


def dispatch_outbox_event(event_id: UUID) -> DispatchResult:
    settings = get_settings()
    with SessionLocal() as session:
        event = session.scalar(
            select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update()
        )
        if event is None:
            return DispatchResult(event_id=event_id, dispatched=False, error="EVENT_NOT_FOUND")
        if event.status == "SENT":
            return DispatchResult(event_id=event_id, dispatched=True)
        if event.status == "DISPATCHING" and not _is_stale(event):
            return DispatchResult(event_id=event_id, dispatched=False, error="IN_PROGRESS")
        if event.status == "FAILED":
            return DispatchResult(
                event_id=event_id,
                dispatched=False,
                error=event.last_error or "TERMINAL_FAILURE",
            )

        event.status = "DISPATCHING"
        event.attempt_count += 1
        event.last_attempt_at = datetime.now(UTC)
        event.last_error = None
        session.commit()
        payload = dict(event.payload_json)
        event_type = event.event_type

    try:
        if event_type == "ticket.received":
            ticket_id = payload["ticket_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                process_ticket_job(UUID(ticket_id), correlation_id)
            else:
                from ticket_agent.workers.tasks import process_ticket_task

                process_ticket_task.apply_async(
                    args=[ticket_id, correlation_id, str(event_id)],
                    task_id=f"ticket-process:{event_id}",
                )
        elif event_type == "knowledge.version.ingest":
            version_id = payload["version_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                from ticket_agent.knowledge.worker import ingest_knowledge_version_job

                ingest_knowledge_version_job(UUID(version_id), correlation_id)
            else:
                from ticket_agent.workers.tasks import ingest_knowledge_version_task

                ingest_knowledge_version_task.apply_async(
                    args=[version_id, correlation_id, str(event_id)],
                    task_id=f"knowledge-ingest:{event_id}",
                )
        elif event_type == "ticket.sync_external":
            ticket_id = payload["ticket_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                from ticket_agent.integrations.worker import sync_ticket_job

                sync_ticket_job(UUID(ticket_id), correlation_id)
            else:
                from ticket_agent.workers.tasks import sync_ticket_task

                sync_ticket_task.apply_async(
                    args=[ticket_id, correlation_id, str(event_id)],
                    task_id=f"ticket-sync:{event_id}",
                )
        elif event_type == "ecommerce.listing.publish":
            task_id = payload["task_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                from ticket_agent.ecommerce.worker import publish_ecommerce_listing_job

                publish_ecommerce_listing_job(UUID(task_id), correlation_id)
            else:
                from ticket_agent.workers.tasks import publish_ecommerce_listing_task

                publish_ecommerce_listing_task.apply_async(
                    args=[task_id, correlation_id, str(event_id)],
                    task_id=f"ecommerce-listing-publish:{event_id}",
                )
        elif event_type == "ecommerce.storyboard.video_render":
            job_id = payload["job_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                from ticket_agent.ecommerce.worker import render_ecommerce_video_job

                render_ecommerce_video_job(UUID(job_id), correlation_id)
            else:
                from ticket_agent.workers.tasks import (
                    render_ecommerce_storyboard_video_task,
                )

                render_ecommerce_storyboard_video_task.apply_async(
                    args=[job_id, correlation_id, str(event_id)],
                    task_id=f"ecommerce-storyboard-video:{event_id}",
                )
        elif event_type == "ecommerce.listing.batch_generate":
            batch_job_id = payload["batch_job_id"]
            correlation_id = payload.get("correlation_id", str(event_id))
            if settings.task_mode == "inline":
                from ticket_agent.ecommerce.worker import (
                    generate_ecommerce_listing_batch_job,
                )

                generate_ecommerce_listing_batch_job(
                    UUID(batch_job_id),
                    correlation_id,
                )
            else:
                from ticket_agent.workers.tasks import (
                    generate_ecommerce_listing_batch_task,
                )

                generate_ecommerce_listing_batch_task.apply_async(
                    args=[batch_job_id, correlation_id, str(event_id)],
                    task_id=f"ecommerce-listing-batch:{event_id}",
                )
        else:
            raise ValueError(f"Unsupported outbox event type: {event_type}")
    except Exception as exc:
        _mark_retry(event_id, f"{type(exc).__name__}: {exc}")
        return DispatchResult(event_id=event_id, dispatched=False, error=str(exc))

    _mark_sent(event_id)
    return DispatchResult(event_id=event_id, dispatched=True)


def dispatch_pending_events(limit: int | None = None) -> list[DispatchResult]:
    settings = get_settings()
    batch_size = limit or settings.outbox_batch_size
    now = datetime.now(UTC)
    stale_before = now - timedelta(minutes=2)

    with SessionLocal() as session:
        events = session.scalars(
            select(OutboxEvent)
            .where(
                or_(
                    (OutboxEvent.status == "PENDING") & (OutboxEvent.available_at <= now),
                    (OutboxEvent.status == "DISPATCHING")
                    & (OutboxEvent.last_attempt_at < stale_before),
                )
            )
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
        ).all()
        event_ids = [event.id for event in events]

    return [dispatch_outbox_event(event_id) for event_id in event_ids]


def _mark_sent(event_id: UUID) -> None:
    with SessionLocal() as session:
        event = session.get(OutboxEvent, event_id)
        if event is None:
            return
        event.status = "SENT"
        event.sent_at = datetime.now(UTC)
        event.last_error = None
        session.commit()


def _mark_retry(event_id: UUID, error: str) -> None:
    settings = get_settings()
    with SessionLocal() as session:
        event = session.get(OutboxEvent, event_id)
        if event is None:
            return
        delay = settings.outbox_retry_base_seconds * (2 ** min(event.attempt_count, 6))
        event.status = "PENDING"
        event.available_at = datetime.now(UTC) + timedelta(seconds=delay)
        event.last_error = error[:2000]
        session.commit()


def _is_stale(event: OutboxEvent) -> bool:
    return (
        event.last_attempt_at is None
        or datetime.now(UTC) - event.last_attempt_at > timedelta(minutes=2)
    )

