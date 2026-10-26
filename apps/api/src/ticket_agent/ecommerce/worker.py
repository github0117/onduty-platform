from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from ticket_agent.audit.service import record_audit
from ticket_agent.ecommerce.models import (
    EcommerceListingBatchItem,
    EcommerceListingBatchJob,
    EcommerceVideoRenderJob,
)
from ticket_agent.ecommerce.schemas import EcommerceListingCreate
from ticket_agent.ecommerce.service import EcommerceService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.redaction import redact_sensitive_text


def publish_ecommerce_listing_job(
    task_id: UUID,
    correlation_id: str,
) -> None:
    with SessionLocal() as session:
        EcommerceService(session).publish(task_id, correlation_id)


def fail_ecommerce_listing_job(task_id: UUID, error: Exception) -> None:
    with SessionLocal() as session:
        EcommerceService(session).fail_publish(task_id, error)


def render_ecommerce_video_job(job_id: UUID, correlation_id: str) -> None:
    with SessionLocal() as session:
        job = session.scalar(
            select(EcommerceVideoRenderJob)
            .where(EcommerceVideoRenderJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status == "SUCCEEDED":
            return
        job.status = "RUNNING"
        job.progress = 10
        job.error_message = None
        job.started_at = job.started_at or datetime.now(UTC)
        job.completed_at = None
        session.commit()

        service = EcommerceService(session)
        try:
            _, _, _, current_generation_id = service._resolve_storyboard_assets(
                job.listing_task_id
            )
            if current_generation_id != job.generation_id:
                raise ApiProblem(
                    status_code=409,
                    code="STORYBOARD_SUPERSEDED_BY_NEW_BATCH",
                    title="Storyboard was superseded",
                    detail="A newer storyboard batch replaced this render job.",
                    retryable=True,
                )
            task, product, storyboard_assets, generation_id = (
                service._resolve_storyboard_assets(
                    job.listing_task_id,
                    generation_id=job.generation_id,
                    source_asset_ids=job.source_asset_ids_json,
                )
            )
            job = session.get(EcommerceVideoRenderJob, job_id)
            if job is None:
                return
            job.progress = 35
            session.commit()

            background_music: bytes | None = None
            if job.background_music_asset_id is not None:
                _, background_music, _ = service.get_asset(
                    job.background_music_asset_id
                )
            job.progress = 70
            session.commit()
            asset = service.render_storyboard_video_snapshot(
                task.id,
                actor_id=job.created_by,
                correlation_id=correlation_id,
                generation_id=generation_id,
                source_asset_ids=job.source_asset_ids_json,
                render_job_id=job.id,
                require_current_generation=True,
                background_music=background_music,
                background_music_asset_id=job.background_music_asset_id,
                background_music_volume=job.background_music_volume,
            )
            job = session.get(EcommerceVideoRenderJob, job_id)
            if job is None:
                return
            job.status = "SUCCEEDED"
            job.progress = 100
            job.asset_id = asset.id
            job.completed_at = datetime.now(UTC)
            record_audit(
                session,
                correlation_id=correlation_id,
                event_type="ecommerce.storyboard.video_job.succeeded",
                actor_type="SERVICE",
                actor_id="digital_employee.ecommerce_creative",
                resource_type="ecommerce_listing_task",
                resource_id=task.id,
                action="render_storyboard_video_job",
                decision="EXECUTED",
                payload={
                    "job_id": str(job.id),
                    "asset_id": str(asset.id),
                    "scene_count": len(storyboard_assets),
                },
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            job = session.get(EcommerceVideoRenderJob, job_id)
            if job is None:
                return
            if isinstance(exc, ApiProblem):
                error_message = f"{exc.code}: {exc.detail}"
            else:
                error_message = f"{type(exc).__name__}: {exc}"
            error_message = redact_sensitive_text(error_message)[:2000]
            job.status = "FAILED"
            job.progress = 100
            job.error_message = error_message
            job.completed_at = datetime.now(UTC)
            record_audit(
                session,
                correlation_id=correlation_id,
                event_type="ecommerce.storyboard.video_job.failed",
                actor_type="SERVICE",
                actor_id="digital_employee.ecommerce_creative",
                resource_type="ecommerce_listing_task",
                resource_id=job.listing_task_id,
                action="render_storyboard_video_job",
                decision="FAILED",
                payload={
                    "job_id": str(job.id),
                    "error_type": type(exc).__name__,
                },
            )
            session.commit()


def generate_ecommerce_listing_batch_job(
    job_id: UUID,
    correlation_id: str,
) -> None:
    with SessionLocal() as session:
        job = session.scalar(
            select(EcommerceListingBatchJob)
            .where(EcommerceListingBatchJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status in {"SUCCEEDED", "FAILED", "PARTIAL"}:
            return
        job.status = "RUNNING"
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_message = None
        session.commit()

        items = session.scalars(
            select(EcommerceListingBatchItem)
            .where(EcommerceListingBatchItem.batch_job_id == job_id)
            .order_by(EcommerceListingBatchItem.created_at)
        ).all()
        service = EcommerceService(session)
        succeeded = 0
        failed = 0
        for queued_item in items:
            item_id = queued_item.id
            item = session.get(EcommerceListingBatchItem, item_id)
            if item is None:
                continue
            if item.status == "SUCCEEDED":
                succeeded += 1
                continue
            item.status = "RUNNING"
            item.started_at = datetime.now(UTC)
            item.error_message = None
            session.commit()
            try:
                task = service.create_listing_task(
                    EcommerceListingCreate(
                        product_id=item.product_id,
                        channel=job.channel,
                        market_code=job.market_code,
                    ),
                    business_unit_id=job.business_unit_id,
                    correlation_id=correlation_id,
                )
                stored_item = session.get(EcommerceListingBatchItem, item_id)
                if stored_item is not None:
                    stored_item.status = "SUCCEEDED"
                    stored_item.listing_task_id = task.id
                    stored_item.completed_at = datetime.now(UTC)
                    session.commit()
                succeeded += 1
            except Exception as exc:
                session.rollback()
                stored_item = session.get(EcommerceListingBatchItem, item_id)
                if stored_item is not None:
                    stored_item.status = "FAILED"
                    stored_item.error_message = redact_sensitive_text(
                        f"{type(exc).__name__}: {exc}"
                    )[:2000]
                    stored_item.completed_at = datetime.now(UTC)
                    session.commit()
                failed += 1

        job = session.get(EcommerceListingBatchJob, job_id)
        if job is None:
            return
        job.succeeded_count = succeeded
        job.failed_count = failed
        job.status = "SUCCEEDED" if failed == 0 else "PARTIAL"
        job.completed_at = datetime.now(UTC)
        record_audit(
            session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.batch_job.completed",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_listing",
            resource_type="ecommerce_listing_batch_job",
            resource_id=job.id,
            action="generate_listing_batch",
            decision=job.status,
            payload={
                "total_count": job.total_count,
                "succeeded_count": succeeded,
                "failed_count": failed,
            },
        )
        session.commit()
