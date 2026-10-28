"""Knowledge gap top list.

Three signals already exist separately: repair tasks opened by failing
evaluations or user feedback, negative feedback clusters, and failed answer
spot checks. Operations need one ranked list to decide what to write next, so
this service merges the open repair queue with feedback clusters and with
failed spot checks that nobody has turned into a repair task yet.

Repair tasks and feedback clusters describe the current backlog and are not
windowed. The spot check signal uses ``days`` because each failed check is an
event rather than a standing state.
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ticket_agent.knowledge.feedback_service import KnowledgeFeedbackService
from ticket_agent.knowledge.repair_service import (
    KnowledgeRepairService,
    normalize_repair_query,
)
from ticket_agent.knowledge.schemas import (
    KnowledgeGapItem,
    KnowledgeGapList,
)
from ticket_agent.tickets.models import AnswerDraft, AnswerQualityEvaluation, Ticket

OPEN_REPAIR_STATUSES = {"OPEN", "IN_REPAIR"}
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
P1_FEEDBACK_REASONS = {"WRONG_ANSWER", "UNSAFE_ANSWER"}


class KnowledgeGapService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(
        self,
        *,
        business_unit_id: str,
        days: int,
        limit: int,
    ) -> KnowledgeGapList:
        items: list[KnowledgeGapItem] = []
        items.extend(self._repair_items(business_unit_id))
        items.extend(self._feedback_items(business_unit_id))
        items.extend(self._spot_check_items(business_unit_id, days))
        items.sort(
            key=lambda item: (
                -item.count,
                PRIORITY_RANK.get(item.priority, 9),
            )
        )
        total = len(items)
        return KnowledgeGapList(items=items[:limit], total=total)

    def _repair_items(self, business_unit_id: str) -> list[KnowledgeGapItem]:
        tasks = KnowledgeRepairService(self.session).list(
            business_unit_id=business_unit_id,
        )
        return [
            KnowledgeGapItem(
                source="REPAIR_TASK",
                title=task.title,
                query=task.query,
                count=task.occurrence_count,
                priority=task.priority,
                status=task.status,
                repair_task_id=task.id,
                draft_id=None,
                knowledge_space_id=task.knowledge_space_id,
            )
            for task in tasks.items
            if task.status in OPEN_REPAIR_STATUSES
        ]

    def _feedback_items(self, business_unit_id: str) -> list[KnowledgeGapItem]:
        clusters = KnowledgeFeedbackService(self.session).clusters(
            business_unit_id=business_unit_id,
        )
        return [
            KnowledgeGapItem(
                source="NEGATIVE_FEEDBACK",
                title=f"负反馈：{cluster.reason_code}",
                query=cluster.latest_query,
                count=cluster.count,
                priority=(
                    "P1"
                    if cluster.reason_code in P1_FEEDBACK_REASONS
                    else "P2"
                ),
                status=None,
                repair_task_id=(
                    cluster.repair_task_ids[0] if cluster.repair_task_ids else None
                ),
                draft_id=None,
                knowledge_space_id=cluster.knowledge_space_id,
            )
            for cluster in clusters.items
        ]

    def _spot_check_items(
        self, business_unit_id: str, days: int
    ) -> list[KnowledgeGapItem]:
        to_at = datetime.now(UTC)
        from_at = to_at - timedelta(days=days)
        rows = self.session.execute(
            select(
                Ticket.subject,
                func.count(AnswerQualityEvaluation.id),
                func.max(AnswerQualityEvaluation.created_at),
                func.sum(
                    case(
                        (AnswerQualityEvaluation.hallucinated.is_(True), 1),
                        else_=0,
                    )
                ),
            )
            .select_from(AnswerQualityEvaluation)
            .join(AnswerDraft, AnswerDraft.id == AnswerQualityEvaluation.draft_id)
            .join(Ticket, Ticket.id == AnswerDraft.ticket_id)
            .where(
                Ticket.business_unit_id == business_unit_id,
                AnswerQualityEvaluation.created_at >= from_at,
                AnswerQualityEvaluation.created_at <= to_at,
                AnswerQualityEvaluation.repair_task_id.is_(None),
                or_(
                    AnswerQualityEvaluation.verdict == "INCORRECT",
                    AnswerQualityEvaluation.hallucinated.is_(True),
                ),
            )
            .group_by(Ticket.subject)
            .order_by(func.count(AnswerQualityEvaluation.id).desc())
        ).all()
        items: list[KnowledgeGapItem] = []
        for subject, count, _, hallucinated_count in rows:
            query = normalize_repair_query(str(subject))
            items.append(
                KnowledgeGapItem(
                    source="SPOT_CHECK",
                    title=f"答案抽检未通过：{query[:120]}",
                    query=query,
                    count=int(cast(int, count)),
                    priority=(
                        "P1"
                        if int(cast(int, hallucinated_count or 0))
                        else "P2"
                    ),
                    status=None,
                    repair_task_id=None,
                    draft_id=None,
                    knowledge_space_id=None,
                )
            )
        return items
