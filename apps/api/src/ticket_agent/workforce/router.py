from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_ticket_writer,
    resolve_business_unit,
)
from ticket_agent.shared.settings import get_settings
from ticket_agent.workforce.schemas import (
    WorkforceTaskCreate,
    WorkforceTaskList,
    WorkforceTaskView,
)
from ticket_agent.workforce.service import WorkforceTaskService
from ticket_agent.workforce.worker import execute_workforce_task_job

router = APIRouter()


@router.post(
    "/workforce/tasks",
    response_model=WorkforceTaskView,
    status_code=status.HTTP_201_CREATED,
)
def plan_workforce_task(
    payload: WorkforceTaskCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> WorkforceTaskView:
    ensure_ticket_writer(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = WorkforceTaskService(db)
    task = service.plan(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="workforce_task.planned",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="workforce_task",
        resource_id=task.id,
        action="plan",
        decision="EXECUTED",
        payload={
            "business_unit_id": task.business_unit_id,
            "supervisor_employee_id": (
                str(task.supervisor_employee_id)
                if task.supervisor_employee_id
                else None
            ),
        },
    )
    db.commit()
    return service.view(task)


@router.get("/workforce/tasks", response_model=WorkforceTaskList)
def list_workforce_tasks(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> WorkforceTaskList:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return WorkforceTaskService(db).list(business_unit_id)


@router.get("/workforce/tasks/{task_id}", response_model=WorkforceTaskView)
def get_workforce_task(
    task_id: UUID,
    db: DbSession,
    principal: Actor,
) -> WorkforceTaskView:
    ensure_ticket_writer(principal)
    service = WorkforceTaskService(db)
    ensure_business_unit_access(
        principal,
        service.get(task_id).business_unit_id,
    )
    return service.view(service.get(task_id))


@router.post(
    "/workforce/tasks/{task_id}/execute",
    response_model=WorkforceTaskView,
)
def execute_workforce_task(
    task_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> WorkforceTaskView:
    ensure_ticket_writer(principal)
    service = WorkforceTaskService(db)
    ensure_business_unit_access(
        principal,
        service.get(task_id).business_unit_id,
    )
    task, newly_queued = service.queue_execution(task_id)
    if not newly_queued:
        return service.view(task)
    request_id = correlation_id(request)
    record_audit(
        db,
        correlation_id=request_id,
        event_type="workforce_task.queued",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="workforce_task",
        resource_id=task.id,
        action="queue_execution",
        decision="EXECUTED",
        payload={"status": task.status},
    )
    db.commit()
    if get_settings().task_mode == "celery":
        from ticket_agent.workers.celery_app import celery_app

        celery_app.send_task(
            "ticket_agent.workforce.execute",
            args=[str(task.id), request_id],
        )
    else:
        background_tasks.add_task(
            execute_workforce_task_job,
            task.id,
            request_id,
        )
    return service.view(task)


@router.post(
    "/workforce/tasks/{task_id}/reassess",
    response_model=WorkforceTaskView,
)
def reassess_workforce_task(
    task_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> WorkforceTaskView:
    ensure_ticket_writer(principal)
    service = WorkforceTaskService(db)
    ensure_business_unit_access(
        principal,
        service.get(task_id).business_unit_id,
    )
    task = service.reassess(task_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="workforce_task.reassessed",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="workforce_task",
        resource_id=task.id,
        action="reassess",
        decision="EXECUTED",
        payload={
            "status": task.status,
            "gap_count": len(
                task.capability_snapshot_json.get("gaps", [])
            ),
        },
    )
    db.commit()
    return service.view(task)


@router.post(
    "/workforce/tasks/{task_id}/retry",
    response_model=WorkforceTaskView,
)
def retry_workforce_task(
    task_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> WorkforceTaskView:
    ensure_ticket_writer(principal)
    service = WorkforceTaskService(db)
    ensure_business_unit_access(
        principal,
        service.get(task_id).business_unit_id,
    )
    task = service.retry_failed(task_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="workforce_task.retry_queued",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="workforce_task",
        resource_id=task.id,
        action="retry",
        decision="EXECUTED",
        payload={"status": task.status},
    )
    db.commit()
    return service.view(task)
