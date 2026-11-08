from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    resolve_business_unit,
)
from ticket_agent.identity.policy import require_capability
from ticket_agent.workflows.models import WorkflowRun, WorkflowStep
from ticket_agent.workflows.schemas import (
    WorkflowReplayResponse,
    WorkflowRunList,
    WorkflowRunView,
    WorkflowStepView,
)
from ticket_agent.workflows.service import (
    get_run,
    list_attention_runs,
    list_run_steps,
    list_runs,
    replay_run,
)

router = APIRouter()


@router.get("/workflows/runs", response_model=WorkflowRunList)
def list_workflow_runs(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowRunList:
    require_capability(principal, "operations.view")
    unit = resolve_business_unit(principal, business_unit_id)
    runs = list_runs(
        db,
        business_unit_id=unit,
        statuses=[status_filter] if status_filter else None,
        limit=limit,
        offset=offset,
    )
    return WorkflowRunList(
        items=_run_list(db, runs),
        limit=limit,
        offset=offset,
    )


@router.get("/workflows/dead-letters", response_model=WorkflowRunList)
def list_workflow_dead_letters(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowRunList:
    require_capability(principal, "operations.view")
    unit = resolve_business_unit(principal, business_unit_id)
    runs = list_attention_runs(
        db,
        business_unit_id=unit,
        limit=limit,
        offset=offset,
    )
    return WorkflowRunList(
        items=_run_list(db, runs),
        limit=limit,
        offset=offset,
    )


@router.get("/workflows/runs/{run_id}", response_model=WorkflowRunView)
def get_workflow_run(
    run_id: UUID,
    db: DbSession,
    principal: Actor,
) -> WorkflowRunView:
    require_capability(principal, "operations.view")
    run = get_run(db, run_id)
    ensure_business_unit_access(principal, run.business_unit_id)
    return _run_view(run, list_run_steps(db, run.id))


@router.post(
    "/workflows/runs/{run_id}/replay",
    response_model=WorkflowReplayResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def replay_workflow_run(
    run_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> WorkflowReplayResponse:
    require_capability(principal, "operations.manage")
    run = get_run(db, run_id)
    ensure_business_unit_access(principal, run.business_unit_id)
    replayed = replay_run(
        db,
        run,
        principal=principal,
        correlation_id=correlation_id(request),
    )
    return WorkflowReplayResponse(
        accepted=True,
        run=_run_view(replayed, list_run_steps(db, replayed.id)),
    )


def _run_list(db: Session, runs: list[WorkflowRun]) -> list[WorkflowRunView]:
    if not runs:
        return []
    steps_by_run: dict[UUID, list[WorkflowStep]] = {}
    for step in db.scalars(
        select(WorkflowStep)
        .where(WorkflowStep.workflow_run_id.in_([run.id for run in runs]))
        .order_by(WorkflowStep.created_at)
    ).all():
        steps_by_run.setdefault(step.workflow_run_id, []).append(step)
    return [_run_view(run, steps_by_run.get(run.id, [])) for run in runs]


def _run_view(run: WorkflowRun, steps: list[WorkflowStep]) -> WorkflowRunView:
    return WorkflowRunView(
        id=run.id,
        business_unit_id=run.business_unit_id,
        workflow_type=run.workflow_type,
        aggregate_type=run.aggregate_type,
        aggregate_id=run.aggregate_id,
        status=run.status,
        current_step=run.current_step,
        context=dict(run.context_json or {}),
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[
            WorkflowStepView(
                id=step.id,
                name=step.name,
                status=step.status,
                attempt_count=step.attempt_count,
                max_attempts=step.max_attempts,
                available_at=step.available_at,
                started_at=step.started_at,
                finished_at=step.finished_at,
                last_error=step.last_error,
                output=step.output_json,
            )
            for step in steps
        ],
    )
