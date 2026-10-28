"""Human spot checks of adopted answer drafts.

Adoption rate says whether agents keep an answer; it does not say whether the
answer is right. This service samples adopted drafts that nobody has checked
yet, stores one verdict per draft, and turns the verdicts into a correctness
and hallucination rate so the operations page can show answer quality next to
adoption and cost.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.knowledge.schemas import (
    AnswerQualityEvaluationCreate,
    AnswerQualityEvaluationView,
    AnswerQualitySampleList,
    AnswerQualitySampleView,
    AnswerQualitySummary,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.tickets.models import AnswerDraft, AnswerQualityEvaluation, Ticket

ADOPTED_STATUSES = ("ACCEPTED", "EDITED_AND_ACCEPTED")
CORRECTNESS_WEIGHTS = {"CORRECT": 1.0, "PARTIAL": 0.5, "INCORRECT": 0.0}


def _rate(numerator: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


class AnswerQualityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _window(self, days: int) -> tuple[datetime, datetime]:
        to_at = datetime.now(UTC)
        return to_at - timedelta(days=days), to_at

    def _pending_conditions(
        self,
        *,
        business_unit_id: str,
        from_at: datetime,
        to_at: datetime,
    ) -> list[Any]:
        return [
            Ticket.business_unit_id == business_unit_id,
            AnswerDraft.status.in_(ADOPTED_STATUSES),
            AnswerDraft.created_at >= from_at,
            AnswerDraft.created_at <= to_at,
            AnswerQualityEvaluation.id.is_(None),
        ]

    def _pending_count(self, conditions: list[Any]) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(AnswerDraft)
                .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
                .join(
                    AnswerQualityEvaluation,
                    AnswerQualityEvaluation.draft_id == AnswerDraft.id,
                    isouter=True,
                )
                .where(*conditions)
            )
            or 0
        )

    def samples(
        self,
        *,
        business_unit_id: str,
        days: int,
        limit: int,
    ) -> AnswerQualitySampleList:
        from_at, to_at = self._window(days)
        conditions = self._pending_conditions(
            business_unit_id=business_unit_id,
            from_at=from_at,
            to_at=to_at,
        )
        rows = self.session.execute(
            select(AnswerDraft, Ticket)
            .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
            .join(
                AnswerQualityEvaluation,
                AnswerQualityEvaluation.draft_id == AnswerDraft.id,
                isouter=True,
            )
            .where(*conditions)
            .order_by(AnswerDraft.created_at.asc())
            .limit(limit)
        ).all()
        items = []
        for draft, ticket in rows:
            items.append(
                AnswerQualitySampleView(
                    draft_id=draft.id,
                    ticket_id=ticket.id,
                    ticket_subject=ticket.subject,
                    draft_text=draft.text,
                    draft_status=draft.status,
                    grounding_status=draft.grounding_status,
                    created_at=draft.created_at,
                    reviewed_at=draft.reviewed_at,
                )
            )
        return AnswerQualitySampleList(
            items=items,
            pending_total=self._pending_count(conditions),
        )

    def summary(self, *, business_unit_id: str, days: int) -> AnswerQualitySummary:
        from_at, to_at = self._window(days)
        adopted_total = int(
            self.session.scalar(
                select(func.count())
                .select_from(AnswerDraft)
                .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
                .where(
                    Ticket.business_unit_id == business_unit_id,
                    AnswerDraft.status.in_(ADOPTED_STATUSES),
                    AnswerDraft.created_at >= from_at,
                    AnswerDraft.created_at <= to_at,
                )
            )
            or 0
        )
        verdict_rows = self.session.execute(
            select(
                AnswerQualityEvaluation.verdict,
                func.count(AnswerQualityEvaluation.id),
            )
            .join(AnswerDraft, AnswerDraft.id == AnswerQualityEvaluation.draft_id)
            .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
            .where(
                Ticket.business_unit_id == business_unit_id,
                AnswerDraft.created_at >= from_at,
                AnswerDraft.created_at <= to_at,
            )
            .group_by(AnswerQualityEvaluation.verdict)
        ).all()
        verdict_counts = {str(verdict): int(count) for verdict, count in verdict_rows}
        evaluated_total = sum(verdict_counts.values())
        hallucinated_total = int(
            self.session.scalar(
                select(func.count())
                .select_from(AnswerQualityEvaluation)
                .join(AnswerDraft, AnswerDraft.id == AnswerQualityEvaluation.draft_id)
                .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
                .where(
                    Ticket.business_unit_id == business_unit_id,
                    AnswerDraft.created_at >= from_at,
                    AnswerDraft.created_at <= to_at,
                    AnswerQualityEvaluation.hallucinated.is_(True),
                )
            )
            or 0
        )
        weighted = sum(
            CORRECTNESS_WEIGHTS.get(verdict, 0.0) * count
            for verdict, count in verdict_counts.items()
        )
        return AnswerQualitySummary(
            business_unit_id=business_unit_id,
            days=days,
            from_at=from_at,
            to_at=to_at,
            adopted_total=adopted_total,
            evaluated_total=evaluated_total,
            coverage_rate=_rate(evaluated_total, adopted_total),
            verdict_counts=verdict_counts,
            correctness_rate=_rate(weighted, evaluated_total),
            hallucination_rate=_rate(hallucinated_total, evaluated_total),
        )

    def record(
        self,
        payload: AnswerQualityEvaluationCreate,
        *,
        actor_id: str,
    ) -> AnswerQualityEvaluationView:
        draft = self.session.get(AnswerDraft, payload.draft_id)
        if draft is None:
            raise ApiProblem(
                status_code=404,
                code="ANSWER_DRAFT_NOT_FOUND",
                title="Answer draft not found",
                detail="The answer draft does not exist in this business unit.",
            )
        ticket = self.session.get(Ticket, draft.ticket_id)
        if ticket is None or ticket.business_unit_id != payload.business_unit_id:
            raise ApiProblem(
                status_code=404,
                code="ANSWER_DRAFT_NOT_FOUND",
                title="Answer draft not found",
                detail="The answer draft does not exist in this business unit.",
            )
        if draft.status not in ADOPTED_STATUSES:
            raise ApiProblem(
                status_code=409,
                code="ANSWER_DRAFT_NOT_ADOPTED",
                title="Answer draft is not adopted",
                detail="Only accepted or edited-and-accepted drafts can be spot checked.",
                context={"status": draft.status},
            )

        existing = self.session.scalar(
            select(AnswerQualityEvaluation).where(
                AnswerQualityEvaluation.draft_id == draft.id
            )
        )
        if existing is None:
            existing = AnswerQualityEvaluation(
                business_unit_id=payload.business_unit_id,
                draft_id=draft.id,
                verdict=payload.verdict,
                hallucinated=payload.hallucinated,
                note=payload.note,
                evaluator_ref=actor_id,
            )
            self.session.add(existing)
            try:
                self.session.commit()
            except IntegrityError:
                # Two reviewers raced on the same draft; the unique constraint
                # keeps one row and the loser turns into an update.
                self.session.rollback()
                existing = self.session.scalar(
                    select(AnswerQualityEvaluation).where(
                        AnswerQualityEvaluation.draft_id == draft.id
                    )
                )
                if existing is None:
                    raise
                self._apply(existing, payload, actor_id)
                self.session.commit()
        else:
            self._apply(existing, payload, actor_id)
            self.session.commit()
        self.session.refresh(existing)
        return self.view(existing)

    def _apply(
        self,
        evaluation: AnswerQualityEvaluation,
        payload: AnswerQualityEvaluationCreate,
        actor_id: str,
    ) -> None:
        evaluation.verdict = payload.verdict
        evaluation.hallucinated = payload.hallucinated
        evaluation.note = payload.note
        evaluation.evaluator_ref = actor_id
        evaluation.updated_at = datetime.now(UTC)

    def view(self, evaluation: AnswerQualityEvaluation) -> AnswerQualityEvaluationView:
        return AnswerQualityEvaluationView(
            id=evaluation.id,
            business_unit_id=evaluation.business_unit_id,
            draft_id=evaluation.draft_id,
            verdict=evaluation.verdict,
            hallucinated=evaluation.hallucinated,
            note=evaluation.note,
            evaluator_ref=evaluation.evaluator_ref,
            created_at=evaluation.created_at,
            updated_at=evaluation.updated_at,
        )
