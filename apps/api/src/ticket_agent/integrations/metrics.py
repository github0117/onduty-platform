from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.models import Ticket


class SyncMetricsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def summary(
        self,
        *,
        business_unit_id: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> dict[str, object]:
        statement = select(Ticket)
        if business_unit_id:
            statement = statement.where(Ticket.business_unit_id == business_unit_id)
        if from_at:
            statement = statement.where(Ticket.created_at >= from_at)
        if to_at:
            statement = statement.where(Ticket.created_at <= to_at)
        tickets = [
            ticket
            for ticket in self.session.scalars(statement).all()
            if ticket.sync_status != "NOT_STARTED"
        ]

        status_counts = {
            status: sum(1 for ticket in tickets if ticket.sync_status == status)
            for status in ("PENDING", "SYNCING", "RETRYING", "SUCCEEDED", "FAILED")
        }
        terminal_count = status_counts["SUCCEEDED"] + status_counts["FAILED"]
        success_rate = (
            status_counts["SUCCEEDED"] / terminal_count
            if terminal_count
            else 0.0
        )
        failure_rate = (
            status_counts["FAILED"] / terminal_count
            if terminal_count
            else 0.0
        )
        alerts: list[str] = []
        if terminal_count and failure_rate >= self.settings.sync_alert_failure_rate:
            alerts.append("SYNC_FAILURE_RATE_HIGH")
        if status_counts["RETRYING"] >= self.settings.sync_alert_retrying_count:
            alerts.append("SYNC_RETRY_BACKLOG_HIGH")

        return {
            "attempted": len(tickets),
            "pending": status_counts["PENDING"],
            "syncing": status_counts["SYNCING"],
            "retrying": status_counts["RETRYING"],
            "succeeded": status_counts["SUCCEEDED"],
            "failed": status_counts["FAILED"],
            "terminal_count": terminal_count,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "average_attempts": (
                sum(ticket.sync_attempts for ticket in tickets) / len(tickets)
                if tickets
                else 0.0
            ),
            "alerts": alerts,
        }

    def business_units(self) -> list[str]:
        return list(
            self.session.scalars(
                select(Ticket.business_unit_id)
                .where(Ticket.sync_status != "NOT_STARTED")
                .distinct()
                .order_by(Ticket.business_unit_id)
            ).all()
        )

