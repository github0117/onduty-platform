from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.efficiency import service
from ticket_agent.efficiency.schemas import (
    AssumptionUpdate,
    AssumptionView,
    EfficiencySummary,
    LedgerPage,
    MaterializeResult,
    RebuildRequest,
)
from ticket_agent.identity.dependencies import (
    ensure_metrics_viewer,
    resolve_business_unit,
)
from ticket_agent.identity.policy import require_capability
from ticket_agent.shared.errors import ApiProblem

router = APIRouter()

MAX_WINDOW_DAYS = 365


def _ensure_efficiency_manager(principal: Actor) -> None:
    require_capability(
        principal,
        "operations.manage",
        title="Efficiency ledger operation denied",
        detail="Efficiency assumptions and rebuild require a supervisor or administrator role.",
    )


def _validate_days(days: int) -> int:
    if days < 1 or days > MAX_WINDOW_DAYS:
        raise ApiProblem(
            status_code=422,
            code="INVALID_WINDOW",
            title="Invalid efficiency window",
            detail=f"days 必须在 1-{MAX_WINDOW_DAYS} 之间。",
        )
    return days


@router.get("/efficiency/summary", response_model=EfficiencySummary)
def get_efficiency_summary(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query()] = 30,
) -> EfficiencySummary:
    ensure_metrics_viewer(principal)
    _validate_days(days)
    return service.summary(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
        days=days,
    )


@router.get("/efficiency/ledger", response_model=LedgerPage)
def get_efficiency_ledger(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    days: Annotated[int, Query()] = 30,
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
) -> LedgerPage:
    ensure_metrics_viewer(principal)
    _validate_days(days)
    if limit < 1 or limit > 200:
        raise ApiProblem(
            status_code=422,
            code="INVALID_PAGINATION",
            title="Invalid pagination",
            detail="limit 必须在 1-200 之间。",
        )
    if offset < 0:
        raise ApiProblem(
            status_code=422,
            code="INVALID_PAGINATION",
            title="Invalid pagination",
            detail="offset 不能为负数。",
        )
    return service.ledger(
        db,
        business_unit_id=resolve_business_unit(principal, business_unit_id),
        days=days,
        limit=limit,
        offset=offset,
    )


@router.get("/efficiency/assumptions", response_model=AssumptionView)
def get_efficiency_assumptions(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> AssumptionView:
    ensure_metrics_viewer(principal)
    return service.assumptions_for(
        db,
        resolve_business_unit(principal, business_unit_id),
    )


@router.put("/efficiency/assumptions", response_model=AssumptionView)
def update_efficiency_assumptions(
    payload: AssumptionUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> AssumptionView:
    _ensure_efficiency_manager(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    view = service.update_assumptions(
        db,
        business_unit_id=business_unit_id,
        payload=payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="efficiency.assumptions.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="efficiency_assumption",
        resource_id=business_unit_id,
        action="update",
        decision="EXECUTED",
        payload={
            "business_unit_id": business_unit_id,
            "version": view.version,
            "currency": view.currency,
            "hourly_labor_cost": view.hourly_labor_cost,
            "minutes_per_ticket": view.minutes_per_ticket,
            "minutes_per_conversation": view.minutes_per_conversation,
            "minutes_per_listing": view.minutes_per_listing,
        },
    )
    db.commit()
    return view


@router.post("/efficiency/rebuild", response_model=MaterializeResult)
def rebuild_efficiency_ledger(
    payload: RebuildRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> MaterializeResult:
    _ensure_efficiency_manager(principal)
    _validate_days(payload.days)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    to_at = datetime.now(UTC)
    from_at = to_at - timedelta(days=payload.days)
    result = service.materialize(
        db,
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="efficiency.ledger.rebuilt",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="efficiency_ledger",
        resource_id=business_unit_id,
        action="rebuild",
        decision="EXECUTED",
        payload={
            "business_unit_id": business_unit_id,
            "days": payload.days,
            "created": result.created,
            "skipped_existing": result.skipped_existing,
            "skipped_ineligible": result.skipped_ineligible,
        },
    )
    db.commit()
    return result
