from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.business_entries.schemas import (
    BusinessServiceEntryCreate,
    BusinessServiceEntryEmployeeInput,
    BusinessServiceEntryUpdate,
    BusinessServiceEntryView,
)
from ticket_agent.business_entries.service import BusinessServiceEntryService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_workspace_viewer,
    resolve_business_unit,
)

router = APIRouter()


@router.get(
    "/business-service-entries",
    response_model=list[BusinessServiceEntryView],
)
def list_business_service_entries(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[BusinessServiceEntryView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return BusinessServiceEntryService(db).list(business_unit_id)


@router.get(
    "/business-service-entries/{entry_id}",
    response_model=BusinessServiceEntryView,
)
def get_business_service_entry(
    entry_id: UUID,
    db: DbSession,
    principal: Actor,
) -> BusinessServiceEntryView:
    ensure_workspace_viewer(principal)
    service = BusinessServiceEntryService(db)
    entry = service.get(entry_id)
    ensure_business_unit_access(principal, entry.business_unit_id)
    return service.view(entry)


@router.post(
    "/business-service-entries",
    response_model=BusinessServiceEntryView,
    status_code=status.HTTP_201_CREATED,
)
def create_business_service_entry(
    payload: BusinessServiceEntryCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> BusinessServiceEntryView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = BusinessServiceEntryService(db)
    entry = service.create(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="business_service_entry.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="business_service_entry",
        resource_id=entry.id,
        action="create",
        decision="EXECUTED",
        payload={"code": entry.code, "employee_count": len(payload.employees)},
    )
    db.commit()
    return service.view(entry)


@router.patch(
    "/business-service-entries/{entry_id}",
    response_model=BusinessServiceEntryView,
)
def update_business_service_entry(
    entry_id: UUID,
    payload: BusinessServiceEntryUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> BusinessServiceEntryView:
    ensure_knowledge_admin(principal)
    service = BusinessServiceEntryService(db)
    entry = service.get(entry_id)
    ensure_business_unit_access(principal, entry.business_unit_id)
    updated = service.update(entry_id, payload)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="business_service_entry.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="business_service_entry",
        resource_id=updated.id,
        action="update",
        decision="EXECUTED",
        payload={"version": updated.version},
    )
    db.commit()
    return service.view(updated)


@router.put(
    "/business-service-entries/{entry_id}/employees",
    response_model=BusinessServiceEntryView,
)
def replace_business_service_entry_employees(
    entry_id: UUID,
    employees: list[BusinessServiceEntryEmployeeInput],
    request: Request,
    db: DbSession,
    principal: Actor,
) -> BusinessServiceEntryView:
    ensure_knowledge_admin(principal)
    service = BusinessServiceEntryService(db)
    entry = service.get(entry_id)
    ensure_business_unit_access(principal, entry.business_unit_id)
    updated = service.replace_employees(entry_id, employees)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="business_service_entry.employees_replaced",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="business_service_entry",
        resource_id=updated.id,
        action="replace_employees",
        decision="EXECUTED",
        payload={"employee_count": len(employees)},
    )
    db.commit()
    return service.view(updated)
