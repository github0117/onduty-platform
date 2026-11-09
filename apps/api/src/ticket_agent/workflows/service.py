"""Workflow executor: idempotent runs, leased steps, retries and replay.

Design notes:

* A run is created once per outbox hand-off (unique constraint on
  ``business_unit_id + workflow_type + idempotency_key``), so a duplicated
  event resumes the existing run instead of starting a twin.
* A step is claimed with a conditional ``UPDATE`` that also increments
  ``attempt_count``; two workers can race and exactly one wins.
* ``lease_expires_at`` is the crash contract: the beat task returns expired
  ``RUNNING`` steps to ``PENDING`` without consuming an attempt.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.identity.models import Principal
from ticket_agent.identity.policy import require_capability
from ticket_agent.shared.db import system_session
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import Ticket
from ticket_agent.workflows.domain import (
    REPLAYABLE_STATUSES,
    StepStatus,
    WorkflowStatus,
)
from ticket_agent.workflows.models import WorkflowRun, WorkflowStep
from ticket_agent.workflows.steps import (
    StepNonRetryableError,
    StepRetryableError,
    WorkflowContext,
    get_step_handler,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StepSpec:
    name: str
    max_attempts: int = 5


@dataclass(frozen=True)
class _ClaimedStep:
    step_id: UUID
    run_id: UUID
    business_unit_id: str
    workflow_type: str
    step_name: str
    attempt: int
    max_attempts: int
    context: dict[str, Any]


def _now() -> datetime:
    return datetime.now(UTC)


def _backoff_seconds(attempt_count: int) -> int:
    base: int = int(get_settings().workflow_retry_base_seconds)
    return int(base * (2 ** max(attempt_count - 1, 0)))


def start_run(
    session: Session,
    *,
    business_unit_id: str,
    workflow_type: str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    idempotency_key: str,
    steps: Sequence[StepSpec],
    context: dict[str, Any] | None = None,
) -> tuple[WorkflowRun, bool]:
    """Create a run once; a concurrent duplicate returns the existing row.

    The insert runs in a savepoint so an ``IntegrityError`` from the unique
    constraint does not poison the caller's transaction.
    """
    payload = dict(context or {})
    existing = _find_run(session, business_unit_id, workflow_type, idempotency_key)
    if existing is not None:
        return existing, False
    run = WorkflowRun(
        business_unit_id=business_unit_id,
        workflow_type=workflow_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        idempotency_key=idempotency_key,
        status=WorkflowStatus.PENDING.value,
        context_json=payload,
    )
    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
            now = _now()
            for spec in steps:
                session.add(
                    WorkflowStep(
                        workflow_run_id=run.id,
                        business_unit_id=business_unit_id,
                        name=spec.name,
                        max_attempts=spec.max_attempts,
                        status=StepStatus.PENDING.value,
                        available_at=now,
                    )
                )
            session.flush()
    except IntegrityError:
        existing = _find_run(session, business_unit_id, workflow_type, idempotency_key)
        if existing is None:
            raise
        return existing, False
    return run, True


def _find_run(
    session: Session,
    business_unit_id: str,
    workflow_type: str,
    idempotency_key: str,
) -> WorkflowRun | None:
    return session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.business_unit_id == business_unit_id,
            WorkflowRun.workflow_type == workflow_type,
            WorkflowRun.idempotency_key == idempotency_key,
        )
    )


def ensure_ticket_sync_run(
    session: Session,
    *,
    ticket_id: UUID,
    correlation_id: str,
    outbox_event_id: UUID | None = None,
    business_unit_id: str | None = None,
) -> tuple[UUID, bool]:
    """Create (or reuse) the workflow that pushes one ticket to the external API."""
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise ApiProblem(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            title="Ticket not found",
            detail=f"Ticket {ticket_id} does not exist.",
        )
    unit = business_unit_id or ticket.business_unit_id
    # One run per outbox hand-off: a duplicated dispatch of the same event
    # resumes the same run, while a manual retry creates a new event and
    # therefore a fresh run even if the previous one is dead-lettered.
    run, created = start_run(
        session,
        business_unit_id=unit,
        workflow_type="ticket_sync",
        aggregate_type="ticket",
        aggregate_id=ticket.id,
        idempotency_key=(
            f"ticket.sync_external:{outbox_event_id or ticket.id}"
        ),
        steps=[
            StepSpec("sync_external"),
            StepSpec("notify", max_attempts=3),
        ],
        context={
            "ticket_id": str(ticket.id),
            "correlation_id": correlation_id,
            "outbox_event_id": str(outbox_event_id) if outbox_event_id else None,
        },
    )
    return run.id, created


def ensure_ecommerce_publish_run(
    session: Session,
    *,
    business_unit_id: str,
    task_id: UUID,
    correlation_id: str,
    outbox_event_id: UUID | None = None,
) -> tuple[UUID, bool]:
    run, created = start_run(
        session,
        business_unit_id=business_unit_id,
        workflow_type="ecommerce_publish",
        aggregate_type="ecommerce_listing_task",
        aggregate_id=task_id,
        idempotency_key=(
            f"ecommerce.listing.publish:{outbox_event_id or task_id}"
        ),
        steps=[StepSpec("publish", max_attempts=3)],
        context={"task_id": str(task_id), "correlation_id": correlation_id},
    )
    return run.id, created


def ensure_knowledge_ingest_run(
    session: Session,
    *,
    business_unit_id: str,
    version_id: UUID,
    correlation_id: str,
    outbox_event_id: UUID | None = None,
) -> tuple[UUID, bool]:
    run, created = start_run(
        session,
        business_unit_id=business_unit_id,
        workflow_type="knowledge_ingest",
        aggregate_type="knowledge_version",
        aggregate_id=version_id,
        idempotency_key=(
            f"knowledge.version.ingest:{outbox_event_id or version_id}"
        ),
        steps=[StepSpec("ingest", max_attempts=3)],
        context={"version_id": str(version_id), "correlation_id": correlation_id},
    )
    return run.id, created


def dispatch_workflow_run(run_id: UUID) -> None:
    """Execute inline, or hand the run to Celery when the deployment uses it."""
    settings = get_settings()
    if settings.task_mode == "inline":
        execute_workflow_run(run_id)
        return
    from ticket_agent.workers.tasks import execute_workflow_run_task

    execute_workflow_run_task.apply_async(
        args=[str(run_id)],
        task_id=f"workflow-run:{run_id}",
    )


def execute_workflow_run(run_id: UUID) -> None:
    while True:
        claimed = _claim_next_step(run_id)
        if claimed is None:
            break
        try:
            output = _run_step(claimed)
        except StepNonRetryableError as exc:
            logger.warning(
                "Workflow step failed permanently: run=%s step=%s attempt=%s error=%s",
                claimed.run_id,
                claimed.step_name,
                claimed.attempt,
                exc,
            )
            _record_failure(claimed, str(exc), retryable=False)
            continue
        except Exception as exc:
            retryable = _is_retryable(exc)
            logger.warning(
                "Workflow step failed: run=%s step=%s attempt=%s retryable=%s error=%s",
                claimed.run_id,
                claimed.step_name,
                claimed.attempt,
                retryable,
                exc,
            )
            _record_failure(claimed, _error_text(exc), retryable=retryable)
            continue
        _record_success(claimed, output)
    _finalise_run(run_id)


def _claim_next_step(run_id: UUID) -> _ClaimedStep | None:
    lease_seconds = get_settings().workflow_step_lease_seconds
    for _ in range(3):
        with system_session() as session:
            return _claim_in_session(session, run_id, lease_seconds)
    return None


def _claim_in_session(
    session: Session,
    run_id: UUID,
    lease_seconds: int,
) -> _ClaimedStep | None:
    now = _now()
    candidate = session.scalar(
        select(WorkflowStep)
        .where(
            WorkflowStep.workflow_run_id == run_id,
            WorkflowStep.status == StepStatus.PENDING.value,
            WorkflowStep.available_at <= now,
        )
        .order_by(WorkflowStep.created_at)
        .limit(1)
    )
    if candidate is None:
        return None
    claimed = session.execute(
        update(WorkflowStep)
        .where(
            WorkflowStep.id == candidate.id,
            WorkflowStep.status == StepStatus.PENDING.value,
            WorkflowStep.attempt_count == candidate.attempt_count,
        )
        .values(
            status=StepStatus.RUNNING.value,
            attempt_count=WorkflowStep.attempt_count + 1,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            started_at=now,
            last_error=None,
            updated_at=now,
        )
    )
    if getattr(claimed, "rowcount", 0) != 1:
        session.rollback()
        return None
    run = session.get(WorkflowRun, run_id)
    if run is None:
        session.rollback()
        return None
    run.status = WorkflowStatus.RUNNING.value
    run.current_step = candidate.name
    run.version += 1
    session.commit()
    return _ClaimedStep(
        step_id=candidate.id,
        run_id=run_id,
        business_unit_id=candidate.business_unit_id,
        workflow_type=run.workflow_type,
        step_name=candidate.name,
        attempt=candidate.attempt_count + 1,
        max_attempts=candidate.max_attempts,
        context=dict(run.context_json or {}),
    )


def claim_step(
    session: Session,
    *,
    run_id: UUID,
    lease_seconds: int | None = None,
) -> _ClaimedStep | None:
    """Claim one pending step of a run with a conditional UPDATE.

    Exposed separately from the ``system_session`` wrapper so PostgreSQL
    concurrency tests can drive two independent sessions against one row.
    """
    return _claim_in_session(
        session,
        run_id,
        lease_seconds or get_settings().workflow_step_lease_seconds,
    )


def _run_step(claimed: _ClaimedStep) -> dict[str, Any]:
    handler = get_step_handler(claimed.workflow_type, claimed.step_name)
    result = handler(
        WorkflowContext(
            run_id=claimed.run_id,
            step_id=claimed.step_id,
            business_unit_id=claimed.business_unit_id,
            workflow_type=claimed.workflow_type,
            step_name=claimed.step_name,
            attempt=claimed.attempt,
            context=claimed.context,
        )
    )
    return result or {}


def _record_success(claimed: _ClaimedStep, output: dict[str, Any]) -> None:
    now = _now()
    with system_session() as session:
        step = session.get(WorkflowStep, claimed.step_id)
        if step is None or step.status != StepStatus.RUNNING.value:
            return
        step.status = StepStatus.SUCCEEDED.value
        step.finished_at = now
        step.lease_expires_at = None
        step.output_json = output
        step.last_error = None
        session.commit()
    logger.info(
        "Workflow step succeeded: run=%s unit=%s step=%s attempt=%s correlation=%s",
        claimed.run_id,
        claimed.business_unit_id,
        claimed.step_name,
        claimed.attempt,
        claimed.context.get("correlation_id"),
    )


def _record_failure(claimed: _ClaimedStep, error: str, *, retryable: bool) -> None:
    now = _now()
    terminal = not retryable or claimed.attempt >= claimed.max_attempts
    with system_session() as session:
        step = session.get(WorkflowStep, claimed.step_id)
        if step is None or step.status != StepStatus.RUNNING.value:
            return
        step.last_error = error[:2000]
        step.lease_expires_at = None
        step.finished_at = now
        if terminal:
            step.status = StepStatus.DEAD_LETTER.value
        else:
            step.status = StepStatus.PENDING.value
            step.available_at = now + timedelta(
                seconds=_backoff_seconds(claimed.attempt)
            )
        run = session.get(WorkflowRun, claimed.run_id)
        if run is not None:
            run.version += 1
            if terminal:
                run.status = WorkflowStatus.DEAD_LETTER.value
        session.commit()
    if terminal:
        logger.error(
            "Workflow step terminal: run=%s unit=%s step=%s status=DEAD_LETTER "
            "attempt=%s correlation=%s error=%s",
            claimed.run_id,
            claimed.business_unit_id,
            claimed.step_name,
            claimed.attempt,
            claimed.context.get("correlation_id"),
            error,
        )
    else:
        logger.info(
            "Workflow step scheduled for retry: run=%s unit=%s step=%s attempt=%s "
            "correlation=%s error=%s",
            claimed.run_id,
            claimed.business_unit_id,
            claimed.step_name,
            claimed.attempt,
            claimed.context.get("correlation_id"),
            error,
        )


def _finalise_run(run_id: UUID) -> None:
    with system_session() as session:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            return
        steps = session.scalars(
            select(WorkflowStep).where(WorkflowStep.workflow_run_id == run_id)
        ).all()
        if not steps:
            return
        if any(step.status == StepStatus.DEAD_LETTER.value for step in steps):
            target = WorkflowStatus.DEAD_LETTER
        elif any(step.status == StepStatus.FAILED.value for step in steps):
            target = WorkflowStatus.FAILED
        elif any(
            step.status in {StepStatus.PENDING.value, StepStatus.RUNNING.value}
            for step in steps
        ):
            return
        else:
            target = WorkflowStatus.SUCCEEDED
        run.status = target.value
        if target == WorkflowStatus.SUCCEEDED:
            run.current_step = None
        session.commit()


def reclaim_stuck_steps() -> list[UUID]:
    with system_session() as session:
        run_ids = reclaim_stuck_steps_in_session(session)
        session.commit()
    if run_ids:
        logger.warning(
            "Workflow leases reclaimed: steps=%s runs=%s",
            len(run_ids),
            len(set(run_ids)),
        )
    return run_ids


def reclaim_stuck_steps_in_session(session: Session) -> list[UUID]:
    """Return leased ``RUNNING`` steps to the queue after a worker died."""
    now = _now()
    stale = (
        WorkflowStep.status == StepStatus.RUNNING.value,
        WorkflowStep.lease_expires_at.is_not(None),
        WorkflowStep.lease_expires_at < now,
        WorkflowStep.attempt_count < WorkflowStep.max_attempts,
    )
    run_ids = list(
        session.scalars(
            select(WorkflowStep.workflow_run_id).where(*stale)
        ).all()
    )
    if not run_ids:
        return []
    session.execute(
        update(WorkflowStep)
        .where(*stale)
        .values(
            status=StepStatus.PENDING.value,
            lease_expires_at=None,
            available_at=now,
            last_error="WORKFLOW_STEP_LEASE_EXPIRED",
            updated_at=now,
        )
    )
    for run in session.scalars(
        select(WorkflowRun).where(
            WorkflowRun.id.in_(run_ids),
            WorkflowRun.status == WorkflowStatus.RUNNING.value,
        )
    ).all():
        run.status = WorkflowStatus.PENDING.value
    return run_ids


def dispatch_due_workflows(limit: int | None = None) -> int:
    """Reclaim expired leases, then dispatch runs with due pending steps."""
    reclaim_stuck_steps()
    settings = get_settings()
    batch_size = limit or settings.workflow_dispatch_batch_size
    now = _now()
    with system_session() as session:
        run_ids = list(
            session.scalars(
                select(WorkflowStep.workflow_run_id)
                .join(
                    WorkflowRun,
                    and_(
                        WorkflowRun.id == WorkflowStep.workflow_run_id,
                        WorkflowRun.business_unit_id == WorkflowStep.business_unit_id,
                    ),
                )
                .where(
                    WorkflowStep.status == StepStatus.PENDING.value,
                    WorkflowStep.available_at <= now,
                    WorkflowRun.status.in_(
                        [
                            WorkflowStatus.PENDING.value,
                            WorkflowStatus.RUNNING.value,
                        ]
                    ),
                )
                .order_by(WorkflowStep.available_at)
                .limit(batch_size)
            ).unique()
        )
    for run_id in run_ids:
        dispatch_workflow_run(run_id)
    return len(run_ids)


def list_runs(
    session: Session,
    *,
    business_unit_id: str,
    statuses: Sequence[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowRun]:
    statement = select(WorkflowRun).where(
        WorkflowRun.business_unit_id == business_unit_id
    )
    if statuses:
        statement = statement.where(WorkflowRun.status.in_(statuses))
    return list(
        session.scalars(
            statement.order_by(WorkflowRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )


def list_runs_for_aggregate(
    session: Session,
    *,
    business_unit_id: str,
    aggregate_type: str,
    aggregate_id: UUID | str,
    limit: int = 20,
) -> list[WorkflowRun]:
    """Read-only listing for one business aggregate (e.g. a ticket).

    Used by surfaces that show workflow progress to actors who can view the
    aggregate itself but hold no ``operations.view`` capability.
    """
    statement = (
        select(WorkflowRun)
        .where(
            WorkflowRun.business_unit_id == business_unit_id,
            WorkflowRun.aggregate_type == aggregate_type,
            WorkflowRun.aggregate_id == str(aggregate_id),
        )
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(statement).all())


def list_attention_runs(
    session: Session,
    *,
    business_unit_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[WorkflowRun]:
    return list_runs(
        session,
        business_unit_id=business_unit_id,
        statuses=[status.value for status in REPLAYABLE_STATUSES],
        limit=limit,
        offset=offset,
    )


def get_run(session: Session, run_id: UUID) -> WorkflowRun:
    run = session.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id)
    )
    if run is None:
        raise ApiProblem(
            status_code=404,
            code="WORKFLOW_RUN_NOT_FOUND",
            title="Workflow run not found",
            detail=f"Workflow run {run_id} does not exist.",
        )
    return run


def list_run_steps(session: Session, run_id: UUID) -> list[WorkflowStep]:
    return list(
        session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_run_id == run_id)
            .order_by(WorkflowStep.created_at)
        ).all()
    )


def replay_run(
    session: Session,
    run: WorkflowRun,
    *,
    principal: Principal,
    correlation_id: str,
) -> WorkflowRun:
    require_capability(principal, "operations.manage")
    settings = get_settings()
    if not settings.workflow_engine_enabled:
        raise ApiProblem(
            status_code=409,
            code="WORKFLOW_ENGINE_DISABLED",
            title="Workflow engine is disabled",
            detail="Replay is unavailable while the workflow engine is switched off.",
        )
    if run.status not in {status.value for status in REPLAYABLE_STATUSES}:
        raise ApiProblem(
            status_code=409,
            code="WORKFLOW_NOT_REPLAYABLE",
            title="Workflow run cannot be replayed",
            detail=f"Only FAILED or DEAD_LETTER runs can be replayed, found {run.status}.",
        )
    now = _now()
    steps = list_run_steps(session, run.id)
    for step in steps:
        if step.status in {StepStatus.FAILED.value, StepStatus.DEAD_LETTER.value}:
            step.status = StepStatus.PENDING.value
            step.attempt_count = 0
            step.available_at = now
            step.lease_expires_at = None
            step.started_at = None
            step.finished_at = None
            step.last_error = None
    run.status = WorkflowStatus.PENDING.value
    run.current_step = None
    run.version += 1
    record_audit(
        session,
        correlation_id=correlation_id,
        event_type="workflow.replayed",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="workflow_run",
        resource_id=run.id,
        action="replay",
        decision="EXECUTED",
        reason_code="MANUAL_REPLAY",
        payload={
            "business_unit_id": run.business_unit_id,
            "workflow_type": run.workflow_type,
            "aggregate_id": run.aggregate_id,
            "version": run.version,
            "steps": [step.name for step in steps],
        },
    )
    session.commit()
    dispatch_workflow_run(run.id)
    return run


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, StepRetryableError):
        return True
    if isinstance(exc, StepNonRetryableError):
        return False
    if isinstance(exc, ApiProblem):
        return exc.retryable
    return True


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, ApiProblem):
        return f"{exc.code}: {exc.detail}"
    return f"{type(exc).__name__}: {exc}"
