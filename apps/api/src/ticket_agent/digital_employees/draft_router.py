from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.draft_schemas import (
    DigitalEmployeeDraftCreate,
    DigitalEmployeeDraftList,
    DigitalEmployeeDraftReview,
    DigitalEmployeeDraftRevisionView,
    DigitalEmployeeDraftUpdate,
    DigitalEmployeeDraftView,
)
from ticket_agent.digital_employees.draft_service import (
    DigitalEmployeeDraftService,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeTemplateView,
    ManagedEmployeeTemplateReview,
    ManagedEmployeeTemplateRevisionView,
    ManagedEmployeeTemplateUpdate,
)
from ticket_agent.digital_employees.template_service import (
    ManagedEmployeeTemplateService,
)
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_ticket_writer,
    resolve_business_unit,
)
from ticket_agent.workforce.service import WorkforceTaskService

router = APIRouter()


@router.post(
    "/workforce/tasks/{task_id}/capability-drafts",
    response_model=DigitalEmployeeDraftView,
    status_code=status.HTTP_201_CREATED,
)
def create_capability_draft(
    task_id: UUID,
    payload: DigitalEmployeeDraftCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    service = DigitalEmployeeDraftService(db)
    task = WorkforceTaskService(db).get(task_id)
    ensure_business_unit_access(principal, task.business_unit_id)
    draft = service.create_from_task(
        task_id,
        payload,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.created",
        "create",
        {
            "required_capability": draft.required_capability,
            "template_code": draft.template_code,
        },
    )
    return service.view(draft)


@router.get(
    "/digital-employee-templates/managed",
    response_model=list[DigitalEmployeeTemplateView],
)
def list_managed_employee_templates(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[DigitalEmployeeTemplateView]:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    service = ManagedEmployeeTemplateService(db)
    return [
        service.view(template)
        for template in service.list(
            business_unit_id,
            include_unpublished=True,
        )
    ]


@router.post(
    "/digital-employee-drafts/{draft_id}/promote-template",
    response_model=DigitalEmployeeTemplateView,
    status_code=status.HTTP_201_CREATED,
)
def promote_employee_draft_to_template(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.promote_from_draft(
        draft_id,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee_template.promoted",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_template",
        resource_id=template.id,
        action="promote_from_draft",
        decision="EXECUTED",
        payload={"source_draft_id": str(draft_id)},
    )
    db.commit()
    return service.view(template)


@router.post(
    "/digital-employee-templates/{template_id}/edit",
    response_model=DigitalEmployeeTemplateView,
)
def edit_managed_employee_template(
    template_id: UUID,
    payload: ManagedEmployeeTemplateUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_template_access(db, principal, template_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.update_draft(
        template_id,
        payload,
        actor_id=principal.actor_id,
    )
    _audit_template(
        db,
        request,
        principal,
        template.id,
        "digital_employee_template.updated",
        "update",
        payload.model_dump(exclude_none=True),
    )
    return service.view(template)


@router.post(
    "/digital-employee-templates/{template_id}/review",
    response_model=DigitalEmployeeTemplateView,
)
def review_managed_employee_template(
    template_id: UUID,
    payload: ManagedEmployeeTemplateReview,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_template_access(db, principal, template_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.review(
        template_id,
        payload,
        actor_id=principal.actor_id,
    )
    _audit_template(
        db,
        request,
        principal,
        template.id,
        "digital_employee_template.reviewed",
        "review",
        {"decision": payload.decision, "note": payload.note},
    )
    return service.view(template)


@router.post(
    "/digital-employee-templates/{template_id}/publish",
    response_model=DigitalEmployeeTemplateView,
)
def publish_managed_employee_template(
    template_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_template_access(db, principal, template_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.publish(
        template_id,
        actor_id=principal.actor_id,
    )
    _audit_template(
        db,
        request,
        principal,
        template.id,
        "digital_employee_template.published",
        "publish",
        {},
    )
    return service.view(template)


@router.post(
    "/digital-employee-templates/{template_id}/rollback",
    response_model=DigitalEmployeeTemplateView,
)
def rollback_managed_employee_template(
    template_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_template_access(db, principal, template_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.rollback(
        template_id,
        actor_id=principal.actor_id,
    )
    _audit_template(
        db,
        request,
        principal,
        template.id,
        "digital_employee_template.disabled",
        "rollback",
        {},
    )
    return service.view(template)


@router.post(
    "/digital-employee-templates/{template_id}/reopen",
    response_model=DigitalEmployeeTemplateView,
)
def reopen_managed_employee_template(
    template_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeTemplateView:
    ensure_knowledge_admin(principal)
    _ensure_template_access(db, principal, template_id)
    service = ManagedEmployeeTemplateService(db)
    template = service.reopen(
        template_id,
        actor_id=principal.actor_id,
    )
    _audit_template(
        db,
        request,
        principal,
        template.id,
        "digital_employee_template.reopened",
        "reopen",
        {},
    )
    return service.view(template)


@router.get(
    "/digital-employee-templates/{template_id}/revisions",
    response_model=list[ManagedEmployeeTemplateRevisionView],
)
def list_managed_employee_template_revisions(
    template_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[ManagedEmployeeTemplateRevisionView]:
    ensure_ticket_writer(principal)
    _ensure_template_access(db, principal, template_id)
    return ManagedEmployeeTemplateService(db).list_revisions(
        template_id
    )


@router.get(
    "/digital-employee-drafts",
    response_model=DigitalEmployeeDraftList,
)
def list_capability_drafts(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> DigitalEmployeeDraftList:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return DigitalEmployeeDraftService(db).list(business_unit_id)


@router.get(
    "/digital-employee-drafts/{draft_id}",
    response_model=DigitalEmployeeDraftView,
)
def get_capability_draft(
    draft_id: UUID,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_ticket_writer(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    return service.view(service.get(draft_id))


@router.post(
    "/digital-employee-drafts/{draft_id}/edit",
    response_model=DigitalEmployeeDraftView,
)
def edit_capability_draft(
    draft_id: UUID,
    payload: DigitalEmployeeDraftUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.update_draft(
        draft_id,
        payload,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.updated",
        "update",
        payload.model_dump(exclude_none=True),
    )
    return service.view(draft)


@router.post(
    "/digital-employee-drafts/{draft_id}/review",
    response_model=DigitalEmployeeDraftView,
)
def review_capability_draft(
    draft_id: UUID,
    payload: DigitalEmployeeDraftReview,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.review(
        draft_id,
        payload,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.reviewed",
        "review",
        {"decision": payload.decision, "note": payload.note},
    )
    return service.view(draft)


@router.post(
    "/digital-employee-drafts/{draft_id}/reopen",
    response_model=DigitalEmployeeDraftView,
)
def reopen_capability_draft(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.reopen(
        draft_id,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.reopened",
        "reopen",
        {},
    )
    return service.view(draft)


@router.post(
    "/digital-employee-drafts/{draft_id}/trial",
    response_model=DigitalEmployeeDraftView,
)
def create_capability_trial(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.create_trial(
        draft_id,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.trial_created",
        "create_trial",
        {"employee_id": str(draft.employee_id)},
    )
    return service.view(draft)


@router.post(
    "/digital-employee-drafts/{draft_id}/evaluate",
    response_model=DigitalEmployeeDraftView,
)
def evaluate_capability_draft(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.evaluate(
        draft_id,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.evaluated",
        "evaluate",
        {
            "passed": draft.evaluation_json.get("passed", False),
            "status": draft.status,
        },
    )
    return service.view(draft)


@router.post(
    "/digital-employee-drafts/{draft_id}/publish",
    response_model=DigitalEmployeeDraftView,
)
def publish_capability_draft(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.publish(
        draft_id,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.published",
        "publish",
        {"employee_id": str(draft.employee_id)},
    )
    return service.view(draft)


@router.get(
    "/digital-employee-drafts/{draft_id}/revisions",
    response_model=list[DigitalEmployeeDraftRevisionView],
)
def list_capability_draft_revisions(
    draft_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[DigitalEmployeeDraftRevisionView]:
    ensure_ticket_writer(principal)
    _ensure_draft_access(db, principal, draft_id)
    return DigitalEmployeeDraftService(db).list_revisions(draft_id)


@router.post(
    "/digital-employee-drafts/{draft_id}/rollback",
    response_model=DigitalEmployeeDraftView,
)
def rollback_capability_draft(
    draft_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeDraftView:
    ensure_knowledge_admin(principal)
    _ensure_draft_access(db, principal, draft_id)
    service = DigitalEmployeeDraftService(db)
    draft = service.rollback(
        draft_id,
        actor_id=principal.actor_id,
    )
    _audit(
        db,
        request,
        principal,
        draft.id,
        "digital_employee_draft.rolled_back",
        "rollback",
        {"employee_id": str(draft.employee_id)},
    )
    return service.view(draft)


def _audit(
    db: DbSession,
    request: Request,
    principal: Actor,
    draft_id: UUID,
    event_type: str,
    action: str,
    payload: dict[str, object],
) -> None:
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type=event_type,
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_draft",
        resource_id=draft_id,
        action=action,
        decision="EXECUTED",
        payload=payload,
    )
    db.commit()


def _audit_template(
    db: DbSession,
    request: Request,
    principal: Actor,
    template_id: UUID,
    event_type: str,
    action: str,
    payload: dict[str, object],
) -> None:
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type=event_type,
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_template",
        resource_id=template_id,
        action=action,
        decision="EXECUTED",
        payload=payload,
    )
    db.commit()


def _ensure_draft_access(
    db: DbSession,
    principal: Actor,
    draft_id: UUID,
) -> None:
    draft = DigitalEmployeeDraftService(db).get(draft_id)
    ensure_business_unit_access(
        principal,
        draft.business_unit_id,
    )


def _ensure_template_access(
    db: DbSession,
    principal: Actor,
    template_id: UUID,
) -> None:
    template = ManagedEmployeeTemplateService(db).get(template_id)
    ensure_business_unit_access(
        principal,
        template.business_unit_id,
    )
