from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.models import KnowledgeFeedback, KnowledgeSpace
from ticket_agent.knowledge.repair_service import KnowledgeRepairService
from ticket_agent.knowledge.schemas import (
    KnowledgeFeedbackClusterList,
    KnowledgeFeedbackClusterView,
    KnowledgeFeedbackCreate,
    KnowledgeFeedbackList,
    KnowledgeFeedbackView,
)
from ticket_agent.shared.errors import ApiProblem


class KnowledgeFeedbackService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        payload: KnowledgeFeedbackCreate,
        *,
        actor_id: str,
    ) -> KnowledgeFeedback:
        self._validate_references(payload)
        feedback = KnowledgeFeedback(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
            ticket_id=payload.ticket_id,
            query=payload.query.strip(),
            answer=payload.answer.strip(),
            rating=payload.rating,
            reason_code=payload.reason_code,
            details=payload.details,
            created_by=actor_id,
        )
        self.session.add(feedback)
        self.session.flush()
        if payload.rating == "NEGATIVE":
            reason_labels = {
                "WRONG_ANSWER": "回答内容错误",
                "MISSING_KNOWLEDGE": "缺少相关知识",
                "UNSAFE_ANSWER": "回答存在风险",
                "OUTDATED_KNOWLEDGE": "知识已经过期",
            }
            task = KnowledgeRepairService(self.session).create_from_feedback(
                business_unit_id=payload.business_unit_id,
                knowledge_space_id=payload.knowledge_space_id,
                title=(
                    "用户负反馈："
                    f"{reason_labels.get(payload.reason_code, '需要改进')}"
                ),
                query=payload.query,
                reason_code=payload.reason_code,
                created_by=actor_id,
            )
            feedback.repair_task_id = task.id
        self.session.commit()
        self.session.refresh(feedback)
        return feedback

    def list(
        self,
        *,
        business_unit_id: str,
        limit: int = 100,
    ) -> KnowledgeFeedbackList:
        items = list(
            self.session.scalars(
                select(KnowledgeFeedback)
                .where(KnowledgeFeedback.business_unit_id == business_unit_id)
                .order_by(KnowledgeFeedback.created_at.desc())
                .limit(limit)
            ).all()
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(KnowledgeFeedback)
            .where(KnowledgeFeedback.business_unit_id == business_unit_id)
        ) or 0
        return KnowledgeFeedbackList(
            items=[self.view(item) for item in items],
            total=total,
        )

    def clusters(
        self,
        *,
        business_unit_id: str,
    ) -> KnowledgeFeedbackClusterList:
        feedback = list(
            self.session.scalars(
                select(KnowledgeFeedback)
                .where(
                    KnowledgeFeedback.business_unit_id == business_unit_id,
                    KnowledgeFeedback.rating == "NEGATIVE",
                )
                .order_by(KnowledgeFeedback.created_at.desc())
            ).all()
        )
        grouped: dict[tuple[object, str], list[KnowledgeFeedback]] = {}
        for item in feedback:
            key = (item.knowledge_space_id, item.reason_code)
            grouped.setdefault(key, []).append(item)
        items = [
            KnowledgeFeedbackClusterView(
                knowledge_space_id=space_id,
                reason_code=reason_code,
                count=len(group),
                repair_task_ids=[
                    item.repair_task_id
                    for item in group
                    if item.repair_task_id is not None
                ],
                latest_query=group[0].query,
            )
            for (space_id, reason_code), group in grouped.items()
        ]
        items.sort(key=lambda item: item.count, reverse=True)
        return KnowledgeFeedbackClusterList(items=items, total=len(feedback))

    def view(self, feedback: KnowledgeFeedback) -> KnowledgeFeedbackView:
        return KnowledgeFeedbackView(
            id=feedback.id,
            business_unit_id=feedback.business_unit_id,
            knowledge_space_id=feedback.knowledge_space_id,
            employee_id=feedback.employee_id,
            ticket_id=feedback.ticket_id,
            query=feedback.query,
            answer=feedback.answer,
            rating=feedback.rating,
            reason_code=feedback.reason_code,
            details=feedback.details,
            repair_task_id=feedback.repair_task_id,
            created_by=feedback.created_by,
            created_at=feedback.created_at,
        )

    def _validate_references(self, payload: KnowledgeFeedbackCreate) -> None:
        if payload.knowledge_space_id is not None:
            space = self.session.get(KnowledgeSpace, payload.knowledge_space_id)
            if space is None or space.business_unit_id != payload.business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="KNOWLEDGE_SPACE_NOT_FOUND",
                    title="Knowledge space not found",
                    detail="The feedback knowledge space does not exist.",
                )
        if payload.employee_id is not None:
            employee = self.session.get(DigitalEmployee, payload.employee_id)
            if employee is None or employee.business_unit_id != payload.business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="DIGITAL_EMPLOYEE_NOT_FOUND",
                    title="Digital employee not found",
                    detail="The feedback employee does not exist.",
                )
