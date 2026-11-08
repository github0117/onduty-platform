"""Workflow gauges derived from the durable run and step tables."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.workflows.domain import StepStatus, WorkflowStatus
from ticket_agent.workflows.models import WorkflowRun, WorkflowStep


class WorkflowMetricsService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def business_units(self) -> list[str]:
        return list(
            self.session.scalars(
                select(WorkflowRun.business_unit_id).distinct()
            ).all()
        )

    def summary(self, *, business_unit_id: str | None = None) -> dict[str, object]:
        run_filter = (
            [WorkflowRun.business_unit_id == business_unit_id]
            if business_unit_id
            else []
        )
        run_rows = self.session.execute(
            select(WorkflowRun.status, func.count(WorkflowRun.id))
            .where(*run_filter)
            .group_by(WorkflowRun.status)
        ).all()
        run_counts = {status: count for status, count in run_rows}
        step_filter = (
            [WorkflowStep.business_unit_id == business_unit_id]
            if business_unit_id
            else []
        )
        step_rows = self.session.execute(
            select(WorkflowStep.status, func.count(WorkflowStep.id))
            .where(*step_filter)
            .group_by(WorkflowStep.status)
        ).all()
        step_counts = {status: count for status, count in step_rows}
        now = datetime.now(UTC)
        pending = self.session.scalar(
            select(func.count(WorkflowStep.id)).where(
                *step_filter,
                WorkflowStep.status == StepStatus.PENDING.value,
            )
        ) or 0
        due = self.session.scalar(
            select(func.count(WorkflowStep.id)).where(
                *step_filter,
                WorkflowStep.status == StepStatus.PENDING.value,
                WorkflowStep.available_at <= now,
            )
        ) or 0
        retrying = self.session.scalar(
            select(func.count(WorkflowStep.id)).where(
                *step_filter,
                WorkflowStep.status == StepStatus.PENDING.value,
                WorkflowStep.attempt_count > 0,
            )
        ) or 0
        oldest = self.session.scalar(
            select(func.min(WorkflowStep.available_at)).where(
                *step_filter,
                WorkflowStep.status == StepStatus.PENDING.value,
            )
        )
        attempts = self.session.scalar(
            select(func.coalesce(func.sum(WorkflowStep.attempt_count), 0)).where(
                *step_filter
            )
        ) or 0
        step_count = sum(step_counts.values()) or 0

        backlog_age = 0.0
        if oldest:
            # SQLite returns naive datetimes for timezone columns.
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            backlog_age = max((now - oldest).total_seconds(), 0.0)

        return {
            "runs_total": sum(run_counts.values()) or 0,
            "runs_pending": run_counts.get(WorkflowStatus.PENDING.value, 0),
            "runs_running": run_counts.get(WorkflowStatus.RUNNING.value, 0),
            "runs_succeeded": run_counts.get(WorkflowStatus.SUCCEEDED.value, 0),
            "runs_failed": run_counts.get(WorkflowStatus.FAILED.value, 0),
            "runs_dead_letter": run_counts.get(WorkflowStatus.DEAD_LETTER.value, 0),
            "steps_total": step_count,
            "steps_pending": pending,
            "steps_due": due,
            "steps_running": step_counts.get(StepStatus.RUNNING.value, 0),
            "steps_succeeded": step_counts.get(StepStatus.SUCCEEDED.value, 0),
            "steps_retrying": retrying,
            "steps_dead_letter": step_counts.get(StepStatus.DEAD_LETTER.value, 0),
            "backlog_age_seconds": backlog_age,
            "step_attempts_total": attempts,
            "average_step_attempts": (
                attempts / step_count if step_count else 0.0
            ),
        }
