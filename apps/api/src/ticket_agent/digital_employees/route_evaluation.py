from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.business_entries.models import (
    BusinessServiceEntry,
    BusinessServiceEntryEmployee,
)
from ticket_agent.digital_employees.models import (
    DigitalEmployee,
    DigitalEmployeeRouteEvaluationCase,
    DigitalEmployeeRouteEvaluationRun,
)
from ticket_agent.digital_employees.router_service import DigitalEmployeeRouter
from ticket_agent.digital_employees.schemas import (
    DigitalEmployeeRouteEvaluationCaseCreate,
    DigitalEmployeeRouteEvaluationCaseUpdate,
    DigitalEmployeeRouteEvaluationCaseView,
    DigitalEmployeeRouteEvaluationResultView,
    DigitalEmployeeRouteEvaluationRunList,
    DigitalEmployeeRouteEvaluationRunView,
)
from ticket_agent.shared.errors import ApiProblem

_MAX_CANDIDATES = 3


def list_route_evaluation_cases(
    session: Session,
    *,
    business_unit_id: str,
    service_entry_id: UUID | None = None,
) -> list[DigitalEmployeeRouteEvaluationCaseView]:
    statement = select(DigitalEmployeeRouteEvaluationCase).where(
        DigitalEmployeeRouteEvaluationCase.business_unit_id == business_unit_id
    )
    if service_entry_id is not None:
        statement = statement.where(
            DigitalEmployeeRouteEvaluationCase.service_entry_id == service_entry_id
        )
    cases = list(
        session.scalars(
            statement.order_by(
                DigitalEmployeeRouteEvaluationCase.created_at,
                DigitalEmployeeRouteEvaluationCase.question,
            )
        ).all()
    )
    names = _employee_names(session, cases)
    return [_case_view(case, names.get(str(case.expected_employee_id), "")) for case in cases]


def create_route_evaluation_case(
    session: Session,
    *,
    business_unit_id: str,
    payload: DigitalEmployeeRouteEvaluationCaseCreate,
) -> DigitalEmployeeRouteEvaluationCaseView:
    _ensure_entry_and_employee(
        session,
        business_unit_id=business_unit_id,
        service_entry_id=payload.service_entry_id,
        expected_employee_id=payload.expected_employee_id,
    )
    case = DigitalEmployeeRouteEvaluationCase(
        business_unit_id=business_unit_id,
        service_entry_id=payload.service_entry_id,
        expected_employee_id=payload.expected_employee_id,
        question=payload.question.strip(),
        notes=payload.notes.strip(),
        enabled=payload.enabled,
    )
    session.add(case)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_CASE_EXISTS",
            title="Route evaluation case exists",
            detail="The same question is already registered for this entry.",
        ) from exc
    session.refresh(case)
    employee = session.get(DigitalEmployee, case.expected_employee_id)
    return _case_view(
        case,
        employee.name if employee is not None else "",
    )


def update_route_evaluation_case(
    session: Session,
    *,
    case_id: UUID,
    payload: DigitalEmployeeRouteEvaluationCaseUpdate,
) -> DigitalEmployeeRouteEvaluationCaseView:
    case = _get_case(session, case_id)
    expected_employee_id = payload.expected_employee_id or case.expected_employee_id
    _ensure_entry_and_employee(
        session,
        business_unit_id=case.business_unit_id,
        service_entry_id=case.service_entry_id,
        expected_employee_id=expected_employee_id,
    )
    if payload.expected_employee_id is not None:
        case.expected_employee_id = payload.expected_employee_id
    if payload.question is not None:
        case.question = payload.question.strip()
    if payload.notes is not None:
        case.notes = payload.notes.strip()
    if payload.enabled is not None:
        case.enabled = payload.enabled
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_CASE_EXISTS",
            title="Route evaluation case exists",
            detail="The same question is already registered for this entry.",
        ) from exc
    session.refresh(case)
    employee = session.get(DigitalEmployee, case.expected_employee_id)
    return _case_view(
        case,
        employee.name if employee is not None else "",
    )


def delete_route_evaluation_case(
    session: Session,
    *,
    case_id: UUID,
) -> None:
    case = _get_case(session, case_id)
    session.delete(case)
    session.commit()


def run_route_evaluation(
    session: Session,
    *,
    business_unit_id: str,
    service_entry_id: UUID,
    actor_id: str,
) -> DigitalEmployeeRouteEvaluationRunView:
    entry = _entry(session, business_unit_id, service_entry_id)
    employee_ids = _entry_employee_ids(session, service_entry_id)
    if not employee_ids:
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_ENTRY_EMPTY",
            title="Route evaluation entry has no employees",
            detail="Bind at least one enabled employee before running evaluation.",
        )
    cases = list(
        session.scalars(
            select(DigitalEmployeeRouteEvaluationCase)
            .where(
                DigitalEmployeeRouteEvaluationCase.business_unit_id == business_unit_id,
                DigitalEmployeeRouteEvaluationCase.service_entry_id == service_entry_id,
                DigitalEmployeeRouteEvaluationCase.enabled.is_(True),
            )
            .order_by(
                DigitalEmployeeRouteEvaluationCase.created_at,
                DigitalEmployeeRouteEvaluationCase.question,
            )
        ).all()
    )
    if not cases:
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_NO_CASES",
            title="Route evaluation has no cases",
            detail="Add enabled evaluation questions before running.",
        )
    names = _employee_names(session, cases)
    router = DigitalEmployeeRouter(session)
    results: list[DigitalEmployeeRouteEvaluationResultView] = []
    for case in cases:
        question = case.question.strip()
        routed = router.route_text(
            business_unit_id=business_unit_id,
            subject=question[:120],
            body=question,
            channel=entry.channel,
            allowed_employee_ids=employee_ids,
            persist_decision=False,
        )
        decision = routed.decision
        candidates = decision.candidates_json[:_MAX_CANDIDATES] if decision is not None else []
        expected_name = names.get(str(case.expected_employee_id), "")
        results.append(
            DigitalEmployeeRouteEvaluationResultView(
                case_id=case.id,
                question=question,
                expected_employee_id=case.expected_employee_id,
                expected_employee_name=expected_name,
                predicted_employee_id=routed.employee.id,
                predicted_employee_name=routed.employee.name,
                matched=routed.employee.id == case.expected_employee_id,
                reason_code=(decision.reason_code if decision is not None else "NO_DECISION"),
                confidence=(decision.confidence if decision is not None else 0.0),
                candidates=candidates,
            )
        )
    passed = sum(1 for item in results if item.matched)
    total = len(results)
    run = DigitalEmployeeRouteEvaluationRun(
        business_unit_id=business_unit_id,
        service_entry_id=service_entry_id,
        total=total,
        passed=passed,
        failed=total - passed,
        accuracy=round(passed / total, 4) if total else 0.0,
        results_json=[item.model_dump(mode="json") for item in results],
        created_by=actor_id,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return _run_view(run)


def list_route_evaluation_runs(
    session: Session,
    *,
    business_unit_id: str,
    service_entry_id: UUID | None = None,
    limit: int = 20,
) -> DigitalEmployeeRouteEvaluationRunList:
    filters = [DigitalEmployeeRouteEvaluationRun.business_unit_id == business_unit_id]
    if service_entry_id is not None:
        filters.append(DigitalEmployeeRouteEvaluationRun.service_entry_id == service_entry_id)
    total = (
        session.scalar(
            select(func.count()).select_from(DigitalEmployeeRouteEvaluationRun).where(*filters)
        )
        or 0
    )
    runs = list(
        session.scalars(
            select(DigitalEmployeeRouteEvaluationRun)
            .where(*filters)
            .order_by(DigitalEmployeeRouteEvaluationRun.created_at.desc())
            .limit(limit)
        ).all()
    )
    return DigitalEmployeeRouteEvaluationRunList(
        items=[_run_view(run) for run in runs],
        total=int(total),
    )


def _case_view(
    case: DigitalEmployeeRouteEvaluationCase,
    expected_employee_name: str,
) -> DigitalEmployeeRouteEvaluationCaseView:
    return DigitalEmployeeRouteEvaluationCaseView(
        id=case.id,
        business_unit_id=case.business_unit_id,
        service_entry_id=case.service_entry_id,
        expected_employee_id=case.expected_employee_id,
        expected_employee_name=expected_employee_name,
        question=case.question,
        notes=case.notes,
        enabled=case.enabled,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _run_view(
    run: DigitalEmployeeRouteEvaluationRun,
) -> DigitalEmployeeRouteEvaluationRunView:
    return DigitalEmployeeRouteEvaluationRunView(
        id=run.id,
        business_unit_id=run.business_unit_id,
        service_entry_id=run.service_entry_id,
        total=run.total,
        passed=run.passed,
        failed=run.failed,
        accuracy=run.accuracy,
        results=[
            DigitalEmployeeRouteEvaluationResultView.model_validate(item)
            for item in run.results_json
        ],
        created_by=run.created_by,
        created_at=run.created_at,
    )


def get_route_evaluation_case(
    session: Session,
    case_id: UUID,
) -> DigitalEmployeeRouteEvaluationCase:
    return _get_case(session, case_id)


def _get_case(
    session: Session,
    case_id: UUID,
) -> DigitalEmployeeRouteEvaluationCase:
    case = session.get(DigitalEmployeeRouteEvaluationCase, case_id)
    if case is None:
        raise ApiProblem(
            status_code=404,
            code="ROUTE_EVALUATION_CASE_NOT_FOUND",
            title="Route evaluation case not found",
            detail="The route evaluation case does not exist.",
        )
    return case


def _entry(
    session: Session,
    business_unit_id: str,
    service_entry_id: UUID,
) -> BusinessServiceEntry:
    entry = session.get(BusinessServiceEntry, service_entry_id)
    if entry is None or entry.business_unit_id != business_unit_id or entry.status != "ACTIVE":
        raise ApiProblem(
            status_code=404,
            code="BUSINESS_ENTRY_NOT_FOUND",
            title="Business service entry not found",
            detail="The business service entry is unavailable.",
        )
    return entry


def _entry_employee_ids(
    session: Session,
    service_entry_id: UUID,
) -> set[UUID]:
    return {
        row.employee_id
        for row in session.scalars(
            select(BusinessServiceEntryEmployee).where(
                BusinessServiceEntryEmployee.service_entry_id == service_entry_id,
                BusinessServiceEntryEmployee.enabled.is_(True),
            )
        ).all()
    }


def _ensure_entry_and_employee(
    session: Session,
    *,
    business_unit_id: str,
    service_entry_id: UUID,
    expected_employee_id: UUID,
) -> None:
    _entry(session, business_unit_id, service_entry_id)
    employee = session.get(DigitalEmployee, expected_employee_id)
    if employee is None or employee.business_unit_id != business_unit_id:
        raise ApiProblem(
            status_code=404,
            code="DIGITAL_EMPLOYEE_NOT_FOUND",
            title="Digital employee not found",
            detail="The expected employee is unavailable.",
        )
    if employee.status != "ACTIVE":
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_EMPLOYEE_INACTIVE",
            title="Expected employee is inactive",
            detail="Only active employees can be used as routing expectations.",
        )
    if expected_employee_id not in _entry_employee_ids(
        session,
        service_entry_id,
    ):
        raise ApiProblem(
            status_code=409,
            code="ROUTE_EVALUATION_EMPLOYEE_NOT_IN_ENTRY",
            title="Expected employee is not in the entry pool",
            detail="Bind the employee to the business entry first.",
        )


def _employee_names(
    session: Session,
    cases: list[DigitalEmployeeRouteEvaluationCase],
) -> dict[str, str]:
    ids = {case.expected_employee_id for case in cases}
    if not ids:
        return {}
    return {
        str(employee.id): employee.name
        for employee in session.scalars(
            select(DigitalEmployee).where(DigitalEmployee.id.in_(ids))
        ).all()
    }
