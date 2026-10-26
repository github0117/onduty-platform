import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.model_gateway.types import ModelGatewayError
from ticket_agent.shared.settings import get_settings

BUDGET_METRICS = ("calls", "tokens", "cost")
BUDGET_PERIODS = ("daily", "weekly", "monthly")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelUsageGuard:
    def __init__(
        self,
        session: Session,
        *,
        employee: DigitalEmployee | None,
        business_unit_id: str | None = None,
        ticket_id: UUID | None,
        correlation_id: str,
    ) -> None:
        self.session = session
        self.employee = employee
        self.business_unit_id = business_unit_id
        self.ticket_id = ticket_id
        self.correlation_id = correlation_id
        self.settings = get_settings()

    def start(self, *, purpose: str) -> float:
        self._assert_budget(purpose)
        return time.monotonic()

    def succeed(
        self,
        *,
        purpose: str,
        provider: str,
        model_name: str,
        usage: TokenUsage,
        started_monotonic: float,
    ) -> None:
        cost = (
            usage.input_tokens
            / 1000
            * self.settings.model_input_cost_per_1k_tokens
            + usage.output_tokens
            / 1000
            * self.settings.model_output_cost_per_1k_tokens
        )
        self._record(
            purpose=purpose,
            provider=provider,
            model_name=model_name,
            status="SUCCEEDED",
            usage=usage,
            cost=cost,
            latency_ms=round((time.monotonic() - started_monotonic) * 1000),
        )

    def fail(
        self,
        *,
        purpose: str,
        provider: str,
        model_name: str,
        started_monotonic: float,
        error_code: str,
    ) -> None:
        self._record(
            purpose=purpose,
            provider=provider,
            model_name=model_name,
            status="FAILED",
            usage=TokenUsage(),
            cost=0.0,
            latency_ms=round((time.monotonic() - started_monotonic) * 1000),
            error_code=error_code,
        )

    def _assert_budget(self, purpose: str) -> None:
        if self.employee is None:
            return
        budget = self.employee.model_profile_json.get("budgets", {})
        if not isinstance(budget, dict):
            return
        now = datetime.now(UTC)
        for period, period_start in _period_starts(now).items():
            current = _usage_totals(
                self.session,
                employee_id=self.employee.id,
                from_at=period_start,
            )
            for metric in BUDGET_METRICS:
                key = f"{period}_{metric}"
                limit = budget.get(key)
                if _exceeds_limit(current[metric], limit):
                    self._record(
                        purpose=purpose,
                        provider="none",
                        model_name="none",
                        status="DENIED",
                        usage=TokenUsage(),
                        cost=0.0,
                        latency_ms=0,
                        error_code="MODEL_BUDGET_EXCEEDED",
                    )
                    raise ModelGatewayError(
                        f"Employee model budget exceeded: {key}",
                        code="MODEL_BUDGET_EXCEEDED",
                    )

    def _record(
        self,
        *,
        purpose: str,
        provider: str,
        model_name: str,
        status: str,
        usage: TokenUsage,
        cost: float,
        latency_ms: int,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self.session.add(
            ModelCall(
                employee_id=self.employee.id if self.employee else None,
                ticket_id=self.ticket_id,
                business_unit_id=(
                    self.employee.business_unit_id
                    if self.employee
                    else self.business_unit_id
                ),
                correlation_id=self.correlation_id,
                purpose=purpose,
                provider=provider,
                model_name=model_name,
                status=status,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                estimated_cost=cost,
                latency_ms=latency_ms,
                error_code=error_code,
                started_at=now,
                completed_at=now,
            )
        )
        self.session.flush()


class ModelUsageService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        *,
        employee_id: UUID | None = None,
        business_unit_id: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> dict[str, object]:
        statement = select(ModelCall)
        if employee_id:
            statement = statement.where(ModelCall.employee_id == employee_id)
        if business_unit_id:
            statement = statement.where(ModelCall.business_unit_id == business_unit_id)
        if from_at:
            statement = statement.where(ModelCall.started_at >= from_at)
        if to_at:
            statement = statement.where(ModelCall.started_at <= to_at)
        calls = list(self.session.scalars(statement).all())
        succeeded = [call for call in calls if call.status == "SUCCEEDED"]
        by_purpose = []
        for purpose in sorted({call.purpose for call in calls}):
            purpose_calls = [call for call in calls if call.purpose == purpose]
            by_purpose.append(
                {
                    "purpose": purpose,
                    "calls": len(purpose_calls),
                    "total_tokens": sum(call.total_tokens for call in purpose_calls),
                    "estimated_cost": sum(
                        call.estimated_cost for call in purpose_calls
                    ),
                }
            )
        employee_statement = select(DigitalEmployee).where(
            DigitalEmployee.status == "ACTIVE"
        )
        if business_unit_id:
            employee_statement = employee_statement.where(
                DigitalEmployee.business_unit_id == business_unit_id
            )
        employees = list(self.session.scalars(employee_statement).all())
        budget_states = [self.budget_status(employee) for employee in employees]
        return {
            "calls": len(calls),
            "succeeded": len(succeeded),
            "failed": sum(call.status == "FAILED" for call in calls),
            "denied": sum(call.status == "DENIED" for call in calls),
            "input_tokens": sum(call.input_tokens for call in calls),
            "output_tokens": sum(call.output_tokens for call in calls),
            "total_tokens": sum(call.total_tokens for call in calls),
            "estimated_cost": sum(call.estimated_cost for call in calls),
            "budget_exceeded": sum(
                bool(status["exceeded"]) for status in budget_states
            ),
            "budget_forecast_alerts": sum(
                bool(status["forecast_alert"]) for status in budget_states
            ),
            "by_purpose": by_purpose,
        }

    def budget_status(
        self,
        employee: DigitalEmployee,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current_time = now or datetime.now(UTC)
        budget = employee.model_profile_json.get("budgets", {})
        if not isinstance(budget, dict):
            budget = {}
        next_month = (current_time.replace(day=28) + timedelta(days=4)).replace(day=1)
        period_ends = {
            "daily": current_time.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            + timedelta(days=1),
            "weekly": current_time.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            - timedelta(days=current_time.weekday())
            + timedelta(days=7),
            "monthly": next_month,
        }
        period_starts = _period_starts(current_time)
        periods: list[dict[str, object]] = []
        budget_exceeded = False
        forecast_alert = False
        for period in BUDGET_PERIODS:
            start = period_starts[period]
            end = period_ends[period]
            usage = _usage_totals(
                self.session,
                employee_id=employee.id,
                from_at=start,
            )
            duration = max((end - start).total_seconds(), 1.0)
            elapsed = min(
                max((current_time - start).total_seconds() / duration, 0.0),
                1.0,
            )
            limits: dict[str, int | float] = {}
            utilizations: dict[str, float] = {}
            projected: dict[str, int | float] = {}
            alerts: list[str] = []
            for metric in BUDGET_METRICS:
                key = f"{period}_{metric}"
                limit = budget.get(key)
                if not _valid_limit(limit):
                    continue
                numeric_limit = float(limit)
                limits[metric] = limit
                utilizations[metric] = (
                    usage[metric] / numeric_limit
                    if numeric_limit > 0
                    else (0.0 if usage[metric] == 0 else 1.0)
                )
                projected[metric] = (
                    usage[metric] / elapsed if elapsed > 0 else usage[metric]
                )
                if usage[metric] >= numeric_limit:
                    budget_exceeded = True
                    alerts.append(f"{key.upper()}_EXCEEDED")
                elif projected[metric] >= numeric_limit:
                    forecast_alert = True
                    alerts.append(f"{key.upper()}_FORECAST")
            periods.append(
                {
                    "period": period,
                    "starts_at": start,
                    "ends_at": end,
                    "elapsed_fraction": round(elapsed, 4),
                    "usage": usage,
                    "limits": limits,
                    "utilization": utilizations,
                    "projected": projected,
                    "alerts": alerts,
                }
            )
        return {
            "employee_id": employee.id,
            "business_unit_id": employee.business_unit_id,
            "exceeded": budget_exceeded,
            "forecast_alert": forecast_alert,
            "periods": periods,
        }


def _period_starts(now: datetime) -> dict[str, datetime]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "daily": day_start,
        "weekly": day_start - timedelta(days=day_start.weekday()),
        "monthly": day_start.replace(day=1),
    }


def _usage_totals(
    session: Session,
    *,
    employee_id: UUID,
    from_at: datetime,
) -> dict[str, int | float]:
    used = session.execute(
        select(
            func.count(ModelCall.id),
            func.coalesce(func.sum(ModelCall.total_tokens), 0),
            func.coalesce(func.sum(ModelCall.estimated_cost), 0.0),
        ).where(
            ModelCall.employee_id == employee_id,
            ModelCall.status == "SUCCEEDED",
            ModelCall.started_at >= from_at,
        )
    ).one()
    return {
        "calls": int(used[0]),
        "tokens": int(used[1]),
        "cost": float(used[2]),
    }


def _valid_limit(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
    )


def _exceeds_limit(current: int | float, limit: object) -> bool:
    return _valid_limit(limit) and current >= float(limit)

