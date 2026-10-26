from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from ticket_agent.agent_skills.schemas import (
    AgentSkillCreate,
    AgentSkillUpdate,
    AgentSkillView,
    EmployeeSkillBindingReplace,
    EmployeeSkillBindingView,
)
from ticket_agent.agent_skills.service import AgentSkillService
from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_workspace_viewer,
    resolve_business_unit,
)

router = APIRouter()


@router.get("/skills", response_model=list[AgentSkillView])
def list_skills(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[AgentSkillView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    service = AgentSkillService(db)
    return [
        service.view(skill)
        for skill in service.list_skills(business_unit_id)
    ]


@router.post(
    "/skills",
    response_model=AgentSkillView,
    status_code=status.HTTP_201_CREATED,
)
def create_skill(
    payload: AgentSkillCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> AgentSkillView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = AgentSkillService(db)
    skill = service.create(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="agent_skill.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_skill",
        resource_id=skill.id,
        action="create",
        decision="EXECUTED",
        payload={"code": skill.code, "version": skill.version},
    )
    db.commit()
    return service.view(skill)


@router.patch("/skills/{skill_id}", response_model=AgentSkillView)
def update_skill(
    skill_id: UUID,
    payload: AgentSkillUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> AgentSkillView:
    ensure_knowledge_admin(principal)
    service = AgentSkillService(db)
    ensure_business_unit_access(
        principal,
        service.get(skill_id).business_unit_id,
    )
    skill = service.update(
        skill_id,
        payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="agent_skill.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_skill",
        resource_id=skill.id,
        action="update",
        decision="EXECUTED",
        payload={"code": skill.code, "version": skill.version},
    )
    db.commit()
    return service.view(skill)


@router.get(
    "/digital-employees/{employee_id}/skills",
    response_model=list[EmployeeSkillBindingView],
)
def list_employee_skills(
    employee_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeSkillBindingView]:
    ensure_workspace_viewer(principal)
    ensure_business_unit_access(
        principal,
        DigitalEmployeeService(db).get(employee_id).business_unit_id,
    )
    return AgentSkillService(db).list_employee_bindings(employee_id)


@router.put(
    "/digital-employees/{employee_id}/skills",
    response_model=list[EmployeeSkillBindingView],
)
def replace_employee_skills(
    employee_id: UUID,
    payload: EmployeeSkillBindingReplace,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeSkillBindingView]:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(
        principal,
        DigitalEmployeeService(db).get(employee_id).business_unit_id,
    )
    service = AgentSkillService(db)
    bindings = service.replace_employee_bindings(
        employee_id,
        [binding.model_dump() for binding in payload.bindings],
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="digital_employee.skills.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee_id,
        action="replace_skills",
        decision="EXECUTED",
        payload={"binding_count": len(bindings)},
    )
    db.commit()
    return bindings
