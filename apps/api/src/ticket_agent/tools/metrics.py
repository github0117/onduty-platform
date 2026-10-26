from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.tickets.models import Ticket
from ticket_agent.tools.models import ToolCall


class ToolMetricsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        *,
        business_unit_id: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> dict[str, object]:
        statement = (
            select(ToolCall)
            .outerjoin(Ticket, Ticket.id == ToolCall.ticket_id)
            .outerjoin(
                DigitalEmployee,
                DigitalEmployee.id == ToolCall.employee_id,
            )
        )
        if business_unit_id:
            statement = statement.where(
                DigitalEmployee.business_unit_id == business_unit_id
            )
        if from_at:
            statement = statement.where(ToolCall.started_at >= from_at)
        if to_at:
            statement = statement.where(ToolCall.started_at <= to_at)
        calls = list(self.session.scalars(statement).all())

        durations = [
            _duration_ms(call)
            for call in calls
            if call.completed_at is not None
        ]
        by_tool = []
        for tool_key in sorted({call.tool_key for call in calls}):
            tool_calls = [call for call in calls if call.tool_key == tool_key]
            tool_durations = [
                _duration_ms(call)
                for call in tool_calls
                if call.completed_at is not None
            ]
            succeeded = sum(call.status == "SUCCEEDED" for call in tool_calls)
            failed = sum(call.status == "FAILED" for call in tool_calls)
            denied = sum(call.status == "DENIED" for call in tool_calls)
            by_tool.append(
                {
                    "tool_key": tool_key,
                    "calls": len(tool_calls),
                    "succeeded": succeeded,
                    "failed": failed,
                    "denied": denied,
                    "success_rate": succeeded / len(tool_calls),
                    "average_duration_ms": _mean(tool_durations),
                    "p95_duration_ms": _percentile(tool_durations, 0.95),
                }
            )

        succeeded = sum(call.status == "SUCCEEDED" for call in calls)
        failed = sum(call.status == "FAILED" for call in calls)
        denied = sum(call.status == "DENIED" for call in calls)
        terminal = succeeded + failed + denied
        return {
            "calls": len(calls),
            "succeeded": succeeded,
            "failed": failed,
            "denied": denied,
            "success_rate": succeeded / terminal if terminal else 0.0,
            "failure_rate": (failed + denied) / terminal if terminal else 0.0,
            "average_duration_ms": _mean(durations),
            "p95_duration_ms": _percentile(durations, 0.95),
            "by_tool": by_tool,
        }


def _duration_ms(call: ToolCall) -> float:
    if call.completed_at is None:
        return 0.0
    return max(0.0, (call.completed_at - call.started_at).total_seconds() * 1000)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * ratio))
    return ordered[index]

