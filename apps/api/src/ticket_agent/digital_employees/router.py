from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.intent_governance import (
    list_route_intent_conflicts,
)
from ticket_agent.digital_employees.route_evaluation import (
    create_route_evaluation_case,
    delete_route_evaluation_case,
    get_route_evaluation_case,
    list_route_evaluation_cases,
    list_route_evaluation_runs,
    run_route_evaluation,
    update_route_evaluation_case,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeConfigurationUpdate,
    DigitalEmployeeCreate,
    DigitalEmployeeFromTemplateCreate,
    DigitalEmployeeRevisionView,
    DigitalEmployeeRouteDecisionList,
    DigitalEmployeeRouteEvaluationCaseCreate,
    DigitalEmployeeRouteEvaluationCaseUpdate,
    DigitalEmployeeRouteEvaluationCaseView,
    DigitalEmployeeRouteEvaluationRunList,
    DigitalEmployeeRouteEvaluationRunRequest,
    DigitalEmployeeRouteEvaluationRunView,
    DigitalEmployeeRouteIntentConflictList,
    DigitalEmployeeRouteRuleUpdate,
    DigitalEmployeeRouteRuleView,
    DigitalEmployeeTemplateView,
    DigitalEmployeeUpdate,
    DigitalEmployeeView,
    RouteEvaluationDataset,
)
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_workspace_viewer,
    resolve_business_unit,
)

router = APIRouter()


@router.get(
    "/digital-employee-templates",
    response_model=list[DigitalEmployeeTemplateView],
)
def list_digital_employee_templates(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> list[DigitalEmployeeTemplateView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return DigitalEmployeeService(db).list_templates(business_unit_id)


@router.get("/digital-employees", response_model=list[DigitalEmployeeView])
def list_digital_employees(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> list[DigitalEmployeeView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    service = DigitalEmployeeService(db)
    return [service.view(employee) for employee in service.list_employees(business_unit_id)]


@router.post(
    "/digital-employees",
    response_model=DigitalEmployeeView,
    status_code=status.HTTP_201_CREATED,
)
def create_digital_employee(
    payload: DigitalEmployeeCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = DigitalEmployeeService(db)
    employee = service.create(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee.id,
        action="create",
        decision="EXECUTED",
        payload={
            "employee_key": employee.employee_key,
            "workflow_key": employee.workflow_key,
            "business_unit_id": employee.business_unit_id,
        },
    )
    db.commit()
    return service.view(employee)


@router.post(
    "/digital-employees/from-template",
    response_model=DigitalEmployeeView,
    status_code=status.HTTP_201_CREATED,
)
def create_digital_employee_from_template(
    payload: DigitalEmployeeFromTemplateCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = DigitalEmployeeService(db)
    employee = service.create_from_template(
        payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.created_from_template",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee.id,
        action="create_from_template",
        decision="EXECUTED",
        payload={
            "employee_key": employee.employee_key,
            "template_code": employee.template_code,
            "business_unit_id": employee.business_unit_id,
            "config_revision": employee.config_revision,
            "instruction_length": len(employee.instruction_text),
        },
    )
    db.commit()
    return service.view(employee)


@router.patch(
    "/digital-employees/{employee_id}",
    response_model=DigitalEmployeeView,
)
def update_digital_employee(
    employee_id: UUID,
    payload: DigitalEmployeeUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeView:
    ensure_knowledge_admin(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    employee = service.update(
        employee_id,
        payload,
        actor_id=principal.actor_id,
    )
    audit_payload = payload.model_dump(exclude_none=True)
    instruction = audit_payload.pop("instruction", None)
    if instruction is not None:
        # 提示词正文进入配置修订即可追溯；审计只记录长度，避免把
        # 可能误填的敏感内容写进日志。
        audit_payload["instruction_length"] = len(instruction)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee.id,
        action="update",
        decision="EXECUTED",
        payload=audit_payload,
    )
    db.commit()
    return service.view(employee)


@router.put(
    "/digital-employees/{employee_id}/configuration",
    response_model=DigitalEmployeeView,
)
def update_digital_employee_configuration(
    employee_id: UUID,
    payload: DigitalEmployeeConfigurationUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeView:
    ensure_knowledge_admin(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    employee = service.update_configuration(
        employee_id,
        payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.configuration.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee.id,
        action="update_configuration",
        decision="EXECUTED",
        payload={
            "status": employee.status,
            "config_revision": employee.config_revision,
            "instruction_length": len(employee.instruction_text),
            "knowledge_binding_count": (
                len(payload.knowledge_bindings) if payload.knowledge_bindings is not None else None
            ),
            "skill_binding_count": (
                len(payload.skill_bindings) if payload.skill_bindings is not None else None
            ),
            "mcp_binding_count": (
                len(payload.mcp_bindings) if payload.mcp_bindings is not None else None
            ),
        },
    )
    db.commit()
    return service.view(employee)


@router.post(
    "/digital-employees/{employee_id}/activate",
    response_model=DigitalEmployeeView,
)
def activate_digital_employee_trial(
    employee_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeView:
    ensure_knowledge_admin(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    employee = service.activate_trial(
        employee_id,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.activation_evaluated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee.id,
        action="activate",
        decision=("EXECUTED" if employee.status == "ACTIVE" else "REJECTED"),
        payload={
            "status": employee.status,
            "evaluation": employee.activation_evaluation_json,
        },
    )
    db.commit()
    return service.view(employee)


@router.get(
    "/digital-employees/{employee_id}/revisions",
    response_model=list[DigitalEmployeeRevisionView],
)
def list_digital_employee_revisions(
    employee_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[DigitalEmployeeRevisionView]:
    ensure_workspace_viewer(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    return service.list_revisions(employee_id)


@router.get(
    "/digital-employees/{employee_id}/route-rule",
    response_model=DigitalEmployeeRouteRuleView,
)
def get_digital_employee_route_rule(
    employee_id: UUID,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeRouteRuleView:
    ensure_workspace_viewer(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    return service.get_route_rule(employee_id)


@router.get(
    "/digital-employee-route-rules",
    response_model=list[DigitalEmployeeRouteRuleView],
)
def list_digital_employee_route_rules(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> list[DigitalEmployeeRouteRuleView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return DigitalEmployeeService(db).list_route_rules(business_unit_id)


@router.put(
    "/digital-employees/{employee_id}/route-rule",
    response_model=DigitalEmployeeRouteRuleView,
)
def update_digital_employee_route_rule(
    employee_id: UUID,
    payload: DigitalEmployeeRouteRuleUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeRouteRuleView:
    ensure_knowledge_admin(principal)
    service = DigitalEmployeeService(db)
    ensure_business_unit_access(
        principal,
        service.get(employee_id).business_unit_id,
    )
    rule = service.update_route_rule(
        employee_id,
        payload,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.route_rule.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_route_rule",
        resource_id=rule.id,
        action="update_route_rule",
        decision="EXECUTED",
        payload={
            "employee_id": str(employee_id),
            "intents": rule.intents,
            "priority": rule.priority,
            "fallback": rule.fallback,
        },
    )
    db.commit()
    return rule


@router.get(
    "/digital-employee-route-intent-conflicts",
    response_model=DigitalEmployeeRouteIntentConflictList,
)
def list_digital_employee_route_intent_conflicts(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> DigitalEmployeeRouteIntentConflictList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return list_route_intent_conflicts(
        db,
        business_unit_id=business_unit_id,
    )


@router.get(
    "/digital-employee-route-evaluation-cases",
    response_model=list[DigitalEmployeeRouteEvaluationCaseView],
)
def list_digital_employee_route_evaluation_cases(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    service_entry_id: Annotated[UUID | None, Query()] = None,
    dataset: Annotated[RouteEvaluationDataset | None, Query()] = None,
) -> list[DigitalEmployeeRouteEvaluationCaseView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return list_route_evaluation_cases(
        db,
        business_unit_id=business_unit_id,
        service_entry_id=service_entry_id,
        dataset=dataset,
    )


@router.post(
    "/digital-employee-route-evaluation-cases",
    response_model=DigitalEmployeeRouteEvaluationCaseView,
    status_code=status.HTTP_201_CREATED,
)
def create_digital_employee_route_evaluation_case(
    payload: DigitalEmployeeRouteEvaluationCaseCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> DigitalEmployeeRouteEvaluationCaseView:
    ensure_knowledge_admin(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    case = create_route_evaluation_case(
        db,
        business_unit_id=business_unit_id,
        payload=payload,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.route_evaluation_case.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_route_evaluation_case",
        resource_id=case.id,
        action="create",
        decision="EXECUTED",
        payload={
            "service_entry_id": str(case.service_entry_id),
            "expected_employee_id": str(case.expected_employee_id),
            "dataset": case.dataset,
        },
    )
    db.commit()
    return case


@router.patch(
    "/digital-employee-route-evaluation-cases/{case_id}",
    response_model=DigitalEmployeeRouteEvaluationCaseView,
)
def update_digital_employee_route_evaluation_case(
    case_id: UUID,
    payload: DigitalEmployeeRouteEvaluationCaseUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> DigitalEmployeeRouteEvaluationCaseView:
    ensure_knowledge_admin(principal)
    existing = get_route_evaluation_case(db, case_id)
    ensure_business_unit_access(principal, existing.business_unit_id)
    case = update_route_evaluation_case(
        db,
        case_id=case_id,
        payload=payload,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.route_evaluation_case.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_route_evaluation_case",
        resource_id=case.id,
        action="update",
        decision="EXECUTED",
        payload=payload.model_dump(exclude_none=True, mode="json"),
    )
    db.commit()
    return case


@router.delete(
    "/digital-employee-route-evaluation-cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_digital_employee_route_evaluation_case(
    case_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> None:
    ensure_knowledge_admin(principal)
    existing = get_route_evaluation_case(db, case_id)
    ensure_business_unit_access(principal, existing.business_unit_id)
    delete_route_evaluation_case(db, case_id=case_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.route_evaluation_case.deleted",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_route_evaluation_case",
        resource_id=case_id,
        action="delete",
        decision="EXECUTED",
        payload={},
    )
    db.commit()


@router.post(
    "/digital-employee-route-evaluation-runs",
    response_model=DigitalEmployeeRouteEvaluationRunView,
    status_code=status.HTTP_201_CREATED,
)
def run_digital_employee_route_evaluation(
    payload: DigitalEmployeeRouteEvaluationRunRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> DigitalEmployeeRouteEvaluationRunView:
    ensure_knowledge_admin(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    run = run_route_evaluation(
        db,
        business_unit_id=business_unit_id,
        service_entry_id=payload.service_entry_id,
        dataset=payload.dataset,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.route_evaluation.completed",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee_route_evaluation_run",
        resource_id=run.id,
        action="run",
        decision="EXECUTED",
        payload={
            "service_entry_id": str(run.service_entry_id),
            "dataset": run.dataset,
            "total": run.total,
            "passed": run.passed,
            "failed": run.failed,
            "accuracy": run.accuracy,
        },
    )
    db.commit()
    return run


@router.get(
    "/digital-employee-route-evaluation-runs",
    response_model=DigitalEmployeeRouteEvaluationRunList,
)
def list_digital_employee_route_evaluation_runs(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    service_entry_id: Annotated[UUID | None, Query()] = None,
    dataset: Annotated[RouteEvaluationDataset | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DigitalEmployeeRouteEvaluationRunList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return list_route_evaluation_runs(
        db,
        business_unit_id=business_unit_id,
        service_entry_id=service_entry_id,
        dataset=dataset,
        limit=limit,
    )


@router.get(
    "/digital-employee-route-decisions",
    response_model=DigitalEmployeeRouteDecisionList,
)
def list_digital_employee_route_decisions(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> DigitalEmployeeRouteDecisionList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    return DigitalEmployeeService(db).list_route_decisions(
        business_unit_id=business_unit_id,
        limit=limit,
    )
