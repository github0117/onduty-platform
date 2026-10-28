from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.customer_service.models import CustomerConversation
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.tickets.models import AnswerDraft, Ticket


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _cost(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


class CustomerValueMetricsService:
    """Adoption and cost metrics for the operations console.

    Adoption is measured on manually reviewed answer drafts; pending and
    auto-accepted drafts stay visible in the payload but never inflate or
    dilute the rate. Cost is read from ``model_calls`` and averaged over
    the same window, so the numbers react to real model usage without a
    separate ledger.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        *,
        business_unit_id: str,
        days: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        to_at = now or datetime.now(UTC)
        from_at = to_at - timedelta(days=days)

        status_rows = self.session.execute(
            select(AnswerDraft.status, func.count(AnswerDraft.id))
            .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
            .where(
                Ticket.business_unit_id == business_unit_id,
                AnswerDraft.created_at >= from_at,
                AnswerDraft.created_at <= to_at,
            )
            .group_by(AnswerDraft.status)
        ).all()
        status_counts = {
            str(status): int(count) for status, count in status_rows
        }
        drafts_total = sum(status_counts.values())
        auto_accepted = status_counts.get("AUTO_ACCEPTED", 0)
        accepted = status_counts.get("ACCEPTED", 0)
        edited = status_counts.get("EDITED_AND_ACCEPTED", 0)
        rejected = status_counts.get("REJECTED", 0)
        escalated = status_counts.get("ESCALATED", 0)
        pending = status_counts.get("NEEDS_REVIEW", 0)
        reviewed = accepted + edited + rejected + escalated
        adopted = accepted + edited
        # AUTO_ACCEPTED drafts never reach a human reviewer, so they are
        # reported separately instead of inflating the human adoption rate.

        grounding_rows = self.session.execute(
            select(AnswerDraft.grounding_status, func.count(AnswerDraft.id))
            .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
            .where(
                Ticket.business_unit_id == business_unit_id,
                AnswerDraft.created_at >= from_at,
                AnswerDraft.created_at <= to_at,
            )
            .group_by(AnswerDraft.grounding_status)
        ).all()
        grounding_counts = {
            str(status): int(count) for status, count in grounding_rows
        }

        tickets_created = int(
            self.session.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(
                    Ticket.business_unit_id == business_unit_id,
                    Ticket.created_at >= from_at,
                    Ticket.created_at <= to_at,
                )
            )
            or 0
        )
        # Archived conversations still count: they happened in the window and
        # consumed model budget, so excluding them would inflate per-conversation cost.
        conversations_created = int(
            self.session.scalar(
                select(func.count())
                .select_from(CustomerConversation)
                .where(
                    CustomerConversation.business_unit_id == business_unit_id,
                    CustomerConversation.created_at >= from_at,
                    CustomerConversation.created_at <= to_at,
                )
            )
            or 0
        )

        calls, tokens, cost = self.session.execute(
            select(
                func.count(ModelCall.id),
                func.coalesce(func.sum(ModelCall.total_tokens), 0),
                func.coalesce(func.sum(ModelCall.estimated_cost), 0.0),
            ).where(
                ModelCall.business_unit_id == business_unit_id,
                ModelCall.started_at >= from_at,
                ModelCall.started_at <= to_at,
            )
        ).one()
        model_calls = int(calls)
        model_tokens = int(tokens)
        estimated_cost = float(cost)

        return {
            "business_unit_id": business_unit_id,
            "days": days,
            "from_at": from_at,
            "to_at": to_at,
            "tickets_created": tickets_created,
            "conversations_created": conversations_created,
            "drafts_total": drafts_total,
            "drafts_auto_accepted": auto_accepted,
            "drafts_pending": pending,
            "drafts_accepted": accepted,
            "drafts_edited_and_accepted": edited,
            "drafts_rejected": rejected,
            "drafts_escalated": escalated,
            "drafts_reviewed": reviewed,
            "adoption_rate": _rate(adopted, reviewed),
            "edit_rate": _rate(edited, adopted),
            "model_calls": model_calls,
            "model_tokens": model_tokens,
            "estimated_cost": estimated_cost,
            "cost_per_conversation": _cost(
                estimated_cost, conversations_created
            ),
            "cost_per_adopted_draft": _cost(estimated_cost, adopted),
            "grounding_counts": grounding_counts,
        }
