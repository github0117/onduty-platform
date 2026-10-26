from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.business_entries.models import (
    BusinessServiceEntry,
    BusinessServiceEntryEmployee,
)
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeRouteRule,
)
from ticket_agent.digital_employees.router_service import (
    digital_employee_intent_breakdown,
)
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeRouteIntentConflict,
    DigitalEmployeeRouteIntentConflictList,
    DigitalEmployeeRouteIntentSuppression,
)


def list_route_intent_conflicts(
    session: Session,
    *,
    business_unit_id: str,
) -> DigitalEmployeeRouteIntentConflictList:
    rows = list(
        session.execute(
            select(DigitalEmployee, DigitalEmployeeRouteRule)
            .outerjoin(
                DigitalEmployeeRouteRule,
                DigitalEmployeeRouteRule.employee_id == DigitalEmployee.id,
            )
            .where(DigitalEmployee.business_unit_id == business_unit_id)
        ).all()
    )
    active_rows = [
        (employee, rule)
        for employee, rule in rows
        if employee.status == "ACTIVE" and rule is not None and rule.enabled
    ]
    employee_names = {str(employee.id): employee.name for employee, _rule in active_rows}
    explicit_owners: dict[str, set[str]] = {}
    for employee, rule in active_rows:
        for term in rule.intents_json:
            normalized = term.strip().casefold()
            if normalized:
                explicit_owners.setdefault(normalized, set()).add(str(employee.id))
    memberships, entry_names = _entry_memberships(
        session,
        business_unit_id=business_unit_id,
    )
    breakdowns = {
        str(employee.id): digital_employee_intent_breakdown(
            employee,
            rule,
            explicit_owners=explicit_owners,
        )
        for employee, rule in active_rows
    }
    term_employees: dict[str, dict[str, str]] = {}
    for employee, _rule in active_rows:
        employee_id = str(employee.id)
        for term in breakdowns[employee_id]["effective"]:
            normalized = term.strip().casefold()
            if not normalized:
                continue
            term_employees.setdefault(normalized, {})[employee_id] = term.strip()
    checked_terms = len(term_employees)
    conflicts: list[DigitalEmployeeRouteIntentConflict] = []
    for normalized, holders in term_employees.items():
        if len(holders) < 2:
            continue
        shared_entries = _shared_entries(
            set(holders),
            memberships=memberships,
        )
        if not shared_entries:
            continue
        conflict_employee_ids = sorted(
            holders,
            key=lambda item: employee_names.get(item, ""),
        )
        explicit_ids = {
            employee_id
            for employee_id in holders
            if _has_explicit_term(
                breakdowns[employee_id]["explicit"],
                normalized,
            )
        }
        source = (
            "EXPLICIT"
            if len(explicit_ids) == len(holders)
            else "INHERITED"
            if not explicit_ids
            else "MIXED"
        )
        conflicts.append(
            DigitalEmployeeRouteIntentConflict(
                term=next(iter(holders.values())),
                employee_ids=[UUID(item) for item in conflict_employee_ids],
                employee_names=[employee_names[item] for item in conflict_employee_ids],
                entry_ids=sorted(shared_entries),
                entry_names=[entry_names[item] for item in sorted(shared_entries)],
                source=source,
            )
        )
    suppressed: list[DigitalEmployeeRouteIntentSuppression] = []
    suppressed_terms: dict[str, dict[str, set[str]]] = {}
    for employee_id, breakdown in breakdowns.items():
        for term in breakdown["suppressed"]:
            normalized = term.strip().casefold()
            if not normalized:
                continue
            bucket = suppressed_terms.setdefault(
                normalized,
                {"affected": set(), "owners": set()},
            )
            bucket["affected"].add(employee_id)
            bucket["owners"].update(explicit_owners.get(normalized, set()) - {employee_id})
    for normalized, bucket in suppressed_terms.items():
        affected_ids = sorted(
            bucket["affected"],
            key=lambda item: employee_names.get(item, ""),
        )
        owner_ids = sorted(
            bucket["owners"] & set(employee_names),
            key=lambda item: employee_names.get(item, ""),
        )
        shared_entries = _shared_entries(
            set(affected_ids) | set(owner_ids),
            memberships=memberships,
        )
        if not shared_entries:
            continue
        suppressed.append(
            DigitalEmployeeRouteIntentSuppression(
                term=next(
                    (
                        term
                        for employee_id in affected_ids
                        for term in breakdowns[employee_id]["suppressed"]
                        if term.strip().casefold() == normalized
                    ),
                    normalized,
                ),
                affected_employee_ids=[UUID(item) for item in affected_ids],
                affected_employee_names=[employee_names[item] for item in affected_ids],
                owner_employee_ids=[UUID(item) for item in owner_ids],
                owner_employee_names=[employee_names[item] for item in owner_ids],
                entry_ids=sorted(shared_entries),
                entry_names=[entry_names[item] for item in sorted(shared_entries)],
            )
        )
    conflicts.sort(key=lambda item: (-len(item.employee_ids), item.term))
    suppressed.sort(
        key=lambda item: (
            -len(item.affected_employee_ids),
            item.term,
        )
    )
    return DigitalEmployeeRouteIntentConflictList(
        business_unit_id=business_unit_id,
        active_employee_count=len(active_rows),
        checked_terms=checked_terms,
        conflicts=conflicts,
        suppressed=suppressed,
    )


def _entry_memberships(
    session: Session,
    *,
    business_unit_id: str,
) -> tuple[dict[str, set[UUID]], dict[UUID, str]]:
    entries = list(
        session.scalars(
            select(BusinessServiceEntry).where(
                BusinessServiceEntry.business_unit_id == business_unit_id,
                BusinessServiceEntry.status == "ACTIVE",
            )
        ).all()
    )
    if not entries:
        return {}, {}
    entry_names = {entry.id: entry.name for entry in entries}
    memberships: dict[str, set[UUID]] = {}
    rows = session.scalars(
        select(BusinessServiceEntryEmployee).where(
            BusinessServiceEntryEmployee.service_entry_id.in_(list(entry_names)),
            BusinessServiceEntryEmployee.enabled.is_(True),
        )
    ).all()
    for row in rows:
        memberships.setdefault(str(row.employee_id), set()).add(row.service_entry_id)
    return memberships, entry_names


def _shared_entries(
    employee_ids: set[str],
    *,
    memberships: dict[str, set[UUID]],
) -> set[UUID]:
    shared: set[UUID] | None = None
    for employee_id in employee_ids:
        entries = memberships.get(employee_id, set())
        shared = entries if shared is None else shared & entries
        if not shared:
            return set()
    return shared or set()


def _has_explicit_term(terms: list[str], normalized: str) -> bool:
    return any(term.strip().casefold() == normalized for term in terms)
