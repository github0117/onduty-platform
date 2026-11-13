from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.identity.dependencies import (
    ensure_service_admin,
    resolve_business_unit,
)
from ticket_agent.scheduling import service
from ticket_agent.scheduling.schemas import (
    OnDutyList,
    RosterCreate,
    RosterDraftUpdate,
    RosterList,
    RosterView,
    SchedulingPolicyUpdate,
    SchedulingPolicyView,
    ShiftTemplateCreate,
    ShiftTemplateList,
    ShiftTemplateUpdate,
    ShiftTemplateView,
)

router = APIRouter()


@router.get("/scheduling/shifts", response_model=ShiftTemplateList)
def list_shift_templates(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> ShiftTemplateList:
    ensure_service_admin(principal)
    return service.list_shifts(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
    )


@router.post("/scheduling/shifts", response_model=ShiftTemplateView)
def create_shift_template(
    payload: ShiftTemplateCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> ShiftTemplateView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    view = service.create_shift(
        db,
        business_unit_id=unit,
        payload=payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="scheduling.shift.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_shift_template",
        resource_id=view.id,
        action="create",
        decision="EXECUTED",
        payload={
            "business_unit_id": unit,
            "name": view.name,
            "version": view.version,
            "start_local": view.start_local.isoformat(timespec="minutes"),
            "end_local": view.end_local.isoformat(timespec="minutes"),
            "cross_day": view.cross_day,
        },
    )
    db.commit()
    return view


@router.patch(
    "/scheduling/shifts/{shift_id}",
    response_model=ShiftTemplateView,
)
def update_shift_template(
    shift_id: UUID,
    payload: ShiftTemplateUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> ShiftTemplateView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    view = service.update_shift(
        db,
        business_unit_id=unit,
        shift_id=shift_id,
        payload=payload,
        actor_id=principal.actor_id,
    )
    archived = payload.status == "ARCHIVED"
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type=(
            "scheduling.shift.archived"
            if archived
            else "scheduling.shift.updated"
        ),
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_shift_template",
        resource_id=view.id,
        action="archive" if archived else "update",
        decision="EXECUTED",
        payload={
            "business_unit_id": unit,
            "name": view.name,
            "version": view.version,
            "status": view.status,
        },
    )
    db.commit()
    return view


@router.get("/scheduling/rosters", response_model=RosterList)
def list_rosters(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    week_start: Annotated[str | None, Query()] = None,
) -> RosterList:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    parsed = service.parse_week_start(week_start) if week_start else None
    return service.list_rosters(
        db,
        business_unit_id=unit,
        week_start=parsed,
    )


@router.post("/scheduling/rosters", response_model=RosterView)
def get_or_create_roster_draft(
    payload: RosterCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> RosterView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    result = service.get_or_create_draft(
        db,
        business_unit_id=unit,
        week_start=payload.week_start,
        timezone_name=payload.timezone,
        actor_id=principal.actor_id,
    )
    if result.changed:
        record_audit(
            db,
            correlation_id=correlation_id(request),
            event_type="scheduling.roster.created",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_type="agent_roster",
            resource_id=result.view.id,
            action="create",
            decision="EXECUTED",
            payload={
                "business_unit_id": unit,
                "week_start": result.view.week_start.isoformat(),
                "timezone": result.view.timezone,
                "version": result.view.version,
            },
        )
    db.commit()
    return result.view


@router.get("/scheduling/rosters/{roster_id}", response_model=RosterView)
def get_roster(
    roster_id: UUID,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> RosterView:
    ensure_service_admin(principal)
    return service.get_roster(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
        roster_id=roster_id,
    )


@router.put(
    "/scheduling/rosters/{roster_id}/draft",
    response_model=RosterView,
)
def save_roster_draft(
    roster_id: UUID,
    payload: RosterDraftUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> RosterView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    result = service.save_draft(
        db,
        business_unit_id=unit,
        roster_id=roster_id,
        payload=payload,
        actor_id=principal.actor_id,
    )
    if result.changed:
        record_audit(
            db,
            correlation_id=correlation_id(request),
            event_type="scheduling.roster.draft_saved",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_type="agent_roster",
            resource_id=result.view.id,
            action="update",
            decision="EXECUTED",
            payload={
                "business_unit_id": unit,
                "week_start": result.view.week_start.isoformat(),
                "version": result.view.version,
                "entry_count": len(result.view.entries),
            },
        )
    db.commit()
    return result.view


@router.post(
    "/scheduling/rosters/{roster_id}/clone",
    response_model=RosterView,
)
def clone_roster(
    roster_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> RosterView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    result = service.clone_roster(
        db,
        business_unit_id=unit,
        source_roster_id=roster_id,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="scheduling.roster.cloned",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_roster",
        resource_id=result.view.id,
        action="clone",
        decision="EXECUTED",
        payload={
            "business_unit_id": unit,
            "week_start": result.view.week_start.isoformat(),
            "source_roster_id": str(roster_id),
            "version": result.view.version,
            "entry_count": len(result.view.entries),
        },
    )
    db.commit()
    return result.view


@router.post(
    "/scheduling/rosters/{roster_id}/publish",
    response_model=RosterView,
)
def publish_roster(
    roster_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> RosterView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    result = service.publish(
        db,
        business_unit_id=unit,
        roster_id=roster_id,
        actor_id=principal.actor_id,
    )
    if result.changed:
        record_audit(
            db,
            correlation_id=correlation_id(request),
            event_type="scheduling.roster.published",
            actor_type="USER",
            actor_id=principal.actor_id,
            resource_type="agent_roster",
            resource_id=result.view.id,
            action="publish",
            decision="EXECUTED",
            payload={
                "business_unit_id": unit,
                "week_start": result.view.week_start.isoformat(),
                "version": result.view.version,
                "entry_count": len(result.view.entries),
            },
        )
    db.commit()
    return result.view


@router.get("/scheduling/policy", response_model=SchedulingPolicyView)
def get_scheduling_policy(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> SchedulingPolicyView:
    ensure_service_admin(principal)
    return service.get_policy(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
    )


@router.put("/scheduling/policy", response_model=SchedulingPolicyView)
def update_scheduling_policy(
    payload: SchedulingPolicyUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> SchedulingPolicyView:
    ensure_service_admin(principal)
    unit = resolve_business_unit(principal, business_unit_id)
    view = service.update_policy(
        db,
        business_unit_id=unit,
        payload=payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="scheduling.policy.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="agent_scheduling_policy",
        resource_id=unit,
        action="update",
        decision="EXECUTED",
        payload={
            "business_unit_id": unit,
            "enforce_published_schedule": view.enforce_published_schedule,
        },
    )
    db.commit()
    return view


@router.get("/scheduling/on-duty", response_model=OnDutyList)
def get_on_duty_agents(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> OnDutyList:
    ensure_service_admin(principal)
    return service.on_duty(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
    )
