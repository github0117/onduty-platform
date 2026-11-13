from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.ecommerce.models import EcommerceListingTask
from ticket_agent.efficiency.models import (
    EfficiencyAssumption,
    EfficiencyLedgerEntry,
)
from ticket_agent.efficiency.schemas import (
    AssumptionUpdate,
    AssumptionView,
    DailyPoint,
    EfficiencySummary,
    EmployeeBreakdown,
    LedgerEntryView,
    LedgerPage,
    MaterializeResult,
    SourceBreakdown,
)
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import Ticket

TICKET_AUTO_RESOLVED = "TICKET_AUTO_RESOLVED"
CONVERSATION_RESOLVED = "CONVERSATION_RESOLVED"
ECOMMERCE_LISTING_COMPLETED = "ECOMMERCE_LISTING_COMPLETED"

RESOLVED_TICKET_STATUSES = ("RESOLVED", "CLOSED")
AUTO_COMPLETED_WORKFLOW_STATE = "COMPLETED"
RESOLVED_CONVERSATION_STATUS = "RESOLVED"
COMPLETED_LISTING_STATUSES = ("SUCCEEDED", "PUBLISHED")

BASIS = [
    "仅统计数字员工独立完成、未被人工接管的产出，单位为人时。",
    "工单需 workflow_state=COMPLETED 且 status 为 RESOLVED/CLOSED。",
    "会话需 status=RESOLVED、无人接管，且未关联已计入工单。",
    "上架任务需 status 为 SUCCEEDED/PUBLISHED。",
    "模型成本取同窗口 model_calls 成功调用的估算成本，不按条目重复分摊。",
    "已生成的账本条目不可修改，后续假设变更只影响新条目。",
]


@dataclass(frozen=True)
class _Candidate:
    source_type: str
    source_id: UUID
    employee_id: UUID | None
    occurred_at: datetime


def assumptions_for(session: Session, business_unit_id: str) -> AssumptionView:
    row = session.scalar(
        select(EfficiencyAssumption).where(
            EfficiencyAssumption.business_unit_id == business_unit_id
        )
    )
    if row is not None:
        return _assumption_view(row, persisted=True)
    settings = get_settings()
    return AssumptionView(
        business_unit_id=business_unit_id,
        currency=settings.efficiency_currency,
        hourly_labor_cost=settings.efficiency_hourly_labor_cost,
        minutes_per_ticket=settings.efficiency_minutes_per_ticket,
        minutes_per_conversation=settings.efficiency_minutes_per_conversation,
        minutes_per_listing=settings.efficiency_minutes_per_listing,
        version=0,
        persisted=False,
    )


def update_assumptions(
    session: Session,
    *,
    business_unit_id: str,
    payload: AssumptionUpdate,
    actor_id: str,
) -> AssumptionView:
    currency = payload.currency.strip().upper()
    if not 3 <= len(currency) <= 8:
        raise ApiProblem(
            status_code=422,
            code="INVALID_ASSUMPTIONS",
            title="Invalid currency",
            detail="currency 必须为 3-8 位字母代码，例如 CNY。",
        )
    row = session.scalar(
        select(EfficiencyAssumption).where(
            EfficiencyAssumption.business_unit_id == business_unit_id
        )
    )
    values = {
        "currency": currency,
        "hourly_labor_cost": payload.hourly_labor_cost,
        "minutes_per_ticket": payload.minutes_per_ticket,
        "minutes_per_conversation": payload.minutes_per_conversation,
        "minutes_per_listing": payload.minutes_per_listing,
        "updated_by": actor_id,
    }
    if row is None:
        row = EfficiencyAssumption(
            business_unit_id=business_unit_id,
            version=1,
            **values,
        )
        session.add(row)
    else:
        row.version += 1
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()
    return _assumption_view(row, persisted=True)


def materialize(
    session: Session,
    *,
    business_unit_id: str,
    from_at: datetime,
    to_at: datetime,
) -> MaterializeResult:
    assumption = assumptions_for(session, business_unit_id)
    candidates, ineligible = _collect_candidates(
        session,
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    existing = _existing_keys(
        session,
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    created = 0
    skipped_existing = 0
    for candidate in candidates:
        key = (candidate.source_type, candidate.source_id)
        if key in existing:
            skipped_existing += 1
            continue
        minutes = _minutes_for(candidate.source_type, assumption)
        cost = round(minutes / 60 * assumption.hourly_labor_cost, 4)
        entry = EfficiencyLedgerEntry(
            business_unit_id=business_unit_id,
            employee_id=candidate.employee_id,
            source_type=candidate.source_type,
            source_id=candidate.source_id,
            occurred_at=candidate.occurred_at,
            human_minutes_saved=minutes,
            labor_cost_saved=cost,
            currency=assumption.currency,
            assumption_snapshot={
                "hourly_labor_cost": assumption.hourly_labor_cost,
                "minutes_saved": minutes,
                "currency": assumption.currency,
                "assumption_version": assumption.version,
                "basis": _basis_for(candidate.source_type),
            },
        )
        try:
            with session.begin_nested():
                session.add(entry)
                session.flush()
        except IntegrityError:
            # Another writer inserted the same source between the existence
            # check and this flush. The savepoint keeps the outer transaction
            # usable so the remaining candidates still get written.
            skipped_existing += 1
            continue
        existing.add(key)
        created += 1
    return MaterializeResult(
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
        created=created,
        skipped_existing=skipped_existing,
        skipped_ineligible=ineligible,
    )


def summary(
    session: Session,
    *,
    business_unit_id: str,
    days: int,
    now: datetime | None = None,
) -> EfficiencySummary:
    to_at = now or datetime.now(UTC)
    from_at = to_at - timedelta(days=days)
    entries = list(
        session.scalars(
            select(EfficiencyLedgerEntry).where(
                EfficiencyLedgerEntry.business_unit_id == business_unit_id,
                EfficiencyLedgerEntry.occurred_at >= from_at,
                EfficiencyLedgerEntry.occurred_at <= to_at,
            )
        ).all()
    )
    model_calls, model_cost = session.execute(
        select(
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.estimated_cost), 0.0),
        ).where(
            ModelCall.business_unit_id == business_unit_id,
            ModelCall.status == "SUCCEEDED",
            ModelCall.started_at >= from_at,
            ModelCall.started_at <= to_at,
        )
    ).one()

    total_minutes = round(sum(float(entry.human_minutes_saved) for entry in entries), 2)
    total_labor = round(sum(float(entry.labor_cost_saved) for entry in entries), 4)
    total_model_cost = round(float(model_cost or 0.0), 6)
    currencies = {entry.currency for entry in entries}
    currency = (
        next(iter(currencies)) if len(currencies) == 1 else assumptions_for(
            session, business_unit_id
        ).currency
    )
    roi = round(total_labor / total_model_cost, 4) if total_model_cost > 0 else None

    employee_names = _employee_names(
        session, {entry.employee_id for entry in entries if entry.employee_id}
    )
    by_source: dict[str, SourceBreakdown] = {}
    by_employee: dict[UUID | None, EmployeeBreakdown] = {}
    by_day: dict[date, DailyPoint] = {}
    for entry in entries:
        minutes = float(entry.human_minutes_saved)
        labor = float(entry.labor_cost_saved)
        source = by_source.get(entry.source_type)
        if source is None:
            by_source[entry.source_type] = SourceBreakdown(
                source_type=entry.source_type,
                entries=1,
                human_minutes_saved=minutes,
                human_hours_saved=round(minutes / 60, 2),
                labor_cost_saved=labor,
            )
        else:
            source.entries += 1
            source.human_minutes_saved = round(source.human_minutes_saved + minutes, 2)
            source.human_hours_saved = round(source.human_minutes_saved / 60, 2)
            source.labor_cost_saved = round(source.labor_cost_saved + labor, 4)

        employee = by_employee.get(entry.employee_id)
        employee_name = (
            employee_names.get(entry.employee_id, "未绑定员工")
            if entry.employee_id
            else "未绑定员工"
        )
        if employee is None:
            by_employee[entry.employee_id] = EmployeeBreakdown(
                employee_id=entry.employee_id,
                employee_name=employee_name,
                entries=1,
                human_minutes_saved=minutes,
                human_hours_saved=round(minutes / 60, 2),
                labor_cost_saved=labor,
            )
        else:
            employee.entries += 1
            employee.human_minutes_saved = round(
                employee.human_minutes_saved + minutes, 2
            )
            employee.human_hours_saved = round(employee.human_minutes_saved / 60, 2)
            employee.labor_cost_saved = round(employee.labor_cost_saved + labor, 4)

        day = _entry_date(entry.occurred_at)
        point = by_day.get(day)
        if point is None:
            by_day[day] = DailyPoint(
                day=day,
                entries=1,
                human_minutes_saved=minutes,
                human_hours_saved=round(minutes / 60, 2),
                labor_cost_saved=labor,
            )
        else:
            point.entries += 1
            point.human_minutes_saved = round(point.human_minutes_saved + minutes, 2)
            point.human_hours_saved = round(point.human_minutes_saved / 60, 2)
            point.labor_cost_saved = round(point.labor_cost_saved + labor, 4)

    return EfficiencySummary(
        business_unit_id=business_unit_id,
        days=days,
        from_at=from_at,
        to_at=to_at,
        currency=currency,
        mixed_currency=len(currencies) > 1,
        entries=len(entries),
        human_minutes_saved=total_minutes,
        human_hours_saved=round(total_minutes / 60, 2),
        labor_cost_saved=total_labor,
        model_cost=total_model_cost,
        model_calls=int(model_calls or 0),
        roi=roi,
        net_saving=round(total_labor - total_model_cost, 4),
        by_source=sorted(by_source.values(), key=lambda item: item.source_type),
        by_employee=sorted(
            by_employee.values(),
            key=lambda item: (-item.human_minutes_saved, item.employee_name),
        ),
        daily=sorted(by_day.values(), key=lambda item: item.day, reverse=True),
        assumptions=assumptions_for(session, business_unit_id),
        basis=BASIS,
    )


def ledger(
    session: Session,
    *,
    business_unit_id: str,
    days: int,
    limit: int,
    offset: int,
    now: datetime | None = None,
) -> LedgerPage:
    to_at = now or datetime.now(UTC)
    from_at = to_at - timedelta(days=days)
    filters = (
        EfficiencyLedgerEntry.business_unit_id == business_unit_id,
        EfficiencyLedgerEntry.occurred_at >= from_at,
        EfficiencyLedgerEntry.occurred_at <= to_at,
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(EfficiencyLedgerEntry)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        session.scalars(
            select(EfficiencyLedgerEntry)
            .where(*filters)
            .order_by(
                EfficiencyLedgerEntry.occurred_at.desc(),
                EfficiencyLedgerEntry.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    )
    employee_names = _employee_names(
        session, {row.employee_id for row in rows if row.employee_id}
    )
    return LedgerPage(
        items=[
            LedgerEntryView(
                id=row.id,
                occurred_at=row.occurred_at,
                source_type=row.source_type,
                source_id=row.source_id,
                employee_id=row.employee_id,
                employee_name=(
                    employee_names.get(row.employee_id, "未绑定员工")
                    if row.employee_id
                    else "未绑定员工"
                ),
                human_minutes_saved=float(row.human_minutes_saved),
                labor_cost_saved=float(row.labor_cost_saved),
                currency=row.currency,
                assumption_version=_snapshot_version(row.assumption_snapshot),
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def materialize_active_business_units(
    session: Session,
    *,
    now: datetime | None = None,
    window_days: int = 7,
) -> dict[str, int]:
    to_at = now or datetime.now(UTC)
    from_at = to_at - timedelta(days=window_days)
    business_units: set[str] = set()
    business_units.update(
        str(row)
        for row in session.scalars(
            select(Ticket.business_unit_id).where(
                Ticket.updated_at >= from_at,
                Ticket.updated_at <= to_at,
            )
        ).all()
    )
    business_units.update(
        str(row)
        for row in session.scalars(
            select(CustomerConversation.business_unit_id).where(
                CustomerConversation.updated_at >= from_at,
                CustomerConversation.updated_at <= to_at,
            )
        ).all()
    )
    business_units.update(
        str(row)
        for row in session.scalars(
            select(EcommerceListingTask.business_unit_id).where(
                EcommerceListingTask.updated_at >= from_at,
                EcommerceListingTask.updated_at <= to_at,
            )
        ).all()
    )
    results: dict[str, int] = {}
    for business_unit_id in sorted(business_units):
        result = materialize(
            session,
            business_unit_id=business_unit_id,
            from_at=from_at,
            to_at=to_at,
        )
        results[business_unit_id] = result.created
    return results


def _assumption_view(
    row: EfficiencyAssumption, *, persisted: bool
) -> AssumptionView:
    return AssumptionView(
        business_unit_id=row.business_unit_id,
        currency=row.currency,
        hourly_labor_cost=float(row.hourly_labor_cost),
        minutes_per_ticket=float(row.minutes_per_ticket),
        minutes_per_conversation=float(row.minutes_per_conversation),
        minutes_per_listing=float(row.minutes_per_listing),
        version=row.version,
        persisted=persisted,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _collect_candidates(
    session: Session,
    *,
    business_unit_id: str,
    from_at: datetime,
    to_at: datetime,
) -> tuple[list[_Candidate], int]:
    candidates: list[_Candidate] = []
    ticket_rows = session.execute(
        select(Ticket.id, Ticket.employee_id, Ticket.updated_at).where(
            Ticket.business_unit_id == business_unit_id,
            Ticket.workflow_state == AUTO_COMPLETED_WORKFLOW_STATE,
            Ticket.status.in_(RESOLVED_TICKET_STATUSES),
            Ticket.updated_at >= from_at,
            Ticket.updated_at <= to_at,
        )
    ).all()
    counted_tickets: set[UUID] = set()
    for ticket_id, employee_id, updated_at in ticket_rows:
        counted_tickets.add(ticket_id)
        candidates.append(
            _Candidate(
                source_type=TICKET_AUTO_RESOLVED,
                source_id=ticket_id,
                employee_id=employee_id,
                occurred_at=updated_at,
            )
        )
    # A ticket may have been ledgered in an earlier window; the conversation
    # pointing at it must still be treated as already counted.
    counted_tickets.update(
        session.scalars(
            select(EfficiencyLedgerEntry.source_id).where(
                EfficiencyLedgerEntry.business_unit_id == business_unit_id,
                EfficiencyLedgerEntry.source_type == TICKET_AUTO_RESOLVED,
            )
        ).all()
    )

    ineligible = 0
    conversation_rows = session.execute(
        select(
            CustomerConversation.id,
            CustomerConversation.employee_id,
            CustomerConversation.updated_at,
            CustomerConversation.current_ticket_id,
        ).where(
            CustomerConversation.business_unit_id == business_unit_id,
            CustomerConversation.status == RESOLVED_CONVERSATION_STATUS,
            CustomerConversation.assigned_agent_id.is_(None),
            CustomerConversation.updated_at >= from_at,
            CustomerConversation.updated_at <= to_at,
        )
    ).all()
    for (
        conversation_id,
        conversation_employee_id,
        conversation_updated_at,
        conversation_ticket_id,
    ) in conversation_rows:
        if (
            conversation_ticket_id is not None
            and conversation_ticket_id in counted_tickets
        ):
            ineligible += 1
            continue
        candidates.append(
            _Candidate(
                source_type=CONVERSATION_RESOLVED,
                source_id=conversation_id,
                employee_id=conversation_employee_id,
                occurred_at=conversation_updated_at,
            )
        )

    listing_rows = session.execute(
        select(
            EcommerceListingTask.id,
            EcommerceListingTask.owner_employee_id,
            EcommerceListingTask.updated_at,
        ).where(
            EcommerceListingTask.business_unit_id == business_unit_id,
            EcommerceListingTask.status.in_(COMPLETED_LISTING_STATUSES),
            EcommerceListingTask.updated_at >= from_at,
            EcommerceListingTask.updated_at <= to_at,
        )
    ).all()
    for task_id, task_employee_id, task_updated_at in listing_rows:
        candidates.append(
            _Candidate(
                source_type=ECOMMERCE_LISTING_COMPLETED,
                source_id=task_id,
                employee_id=task_employee_id,
                occurred_at=task_updated_at,
            )
        )
    return candidates, ineligible


def _existing_keys(
    session: Session,
    *,
    business_unit_id: str,
    from_at: datetime,
    to_at: datetime,
) -> set[tuple[str, UUID]]:
    rows = session.execute(
        select(
            EfficiencyLedgerEntry.source_type,
            EfficiencyLedgerEntry.source_id,
        ).where(
            EfficiencyLedgerEntry.business_unit_id == business_unit_id,
            EfficiencyLedgerEntry.occurred_at >= from_at,
            EfficiencyLedgerEntry.occurred_at <= to_at,
        )
    ).all()
    return {(str(source_type), source_id) for source_type, source_id in rows}


def _minutes_for(source_type: str, assumption: AssumptionView) -> float:
    if source_type == TICKET_AUTO_RESOLVED:
        return float(assumption.minutes_per_ticket)
    if source_type == CONVERSATION_RESOLVED:
        return float(assumption.minutes_per_conversation)
    return float(assumption.minutes_per_listing)


def _basis_for(source_type: str) -> str:
    if source_type == TICKET_AUTO_RESOLVED:
        return "数字员工完成工单处理，未发生人工接管。"
    if source_type == CONVERSATION_RESOLVED:
        return "数字员工完成会话并标记解决，未发生人工接管。"
    return "数字员工完成电商上架任务内容生成与发布。"


def _employee_names(session: Session, employee_ids: set[UUID]) -> dict[UUID, str]:
    if not employee_ids:
        return {}
    rows = session.execute(
        select(DigitalEmployee.id, DigitalEmployee.name).where(
            DigitalEmployee.id.in_(employee_ids)
        )
    ).all()
    names: dict[UUID, str] = {}
    for employee_id, name in rows:
        if employee_id is not None:
            names[employee_id] = name
    return names


def _entry_date(value: datetime) -> date:
    return value.date()


def _snapshot_version(snapshot: dict[str, object] | None) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    version = snapshot.get("assumption_version")
    if isinstance(version, int):
        return version
    return None
