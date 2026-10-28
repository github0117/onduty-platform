import hashlib
import re
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ticket_agent.knowledge.models import (
    KnowledgeEvaluationCase,
    KnowledgeEvaluationRun,
    KnowledgeFeedback,
    KnowledgeRepairTask,
)
from ticket_agent.knowledge.schemas import (
    KnowledgeRepairTaskList,
    KnowledgeRepairTaskUpdate,
    KnowledgeRepairTaskView,
)
from ticket_agent.shared.errors import ApiProblem


class KnowledgeRepairService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_from_evaluation_failures(
        self,
        *,
        run: KnowledgeEvaluationRun,
        cases: list[KnowledgeEvaluationCase],
        scored_cases: list[dict[str, Any]],
    ) -> list[KnowledgeRepairTask]:
        tasks: list[KnowledgeRepairTask] = []
        for case, score in zip(cases, scored_cases, strict=True):
            passed = score.get("passed")
            if passed is None:
                # Scores produced before the dataset split only carried the
                # title-level recall.
                no_grounding_correct = cast(
                    bool | None, score.get("no_grounding_correct")
                )
                passed = (
                    no_grounding_correct
                    if case.expect_no_grounding
                    else float(score.get("recall_at_k", 0.0)) >= 1.0
                )
            if passed:
                continue
            title = f"知识评测失败：{case.name}"
            existing = self._find_reusable(
                business_unit_id=run.business_unit_id,
                knowledge_space_id=case.knowledge_space_id,
                normalized_query=normalize_repair_query(case.query),
            )
            if existing is not None:
                existing.evaluation_run_id = run.id
                existing.evaluation_case_id = case.id
                existing.expected_titles_json = case.expected_titles_json
                existing.returned_titles_json = [
                    str(value)
                    for value in cast(
                        list[object],
                        score.get("returned_titles", []),
                    )
                ]
                if existing.status == "CLOSED":
                    existing.status = "OPEN"
                    existing.resolved_at = None
                    existing.resolution_note = "评测问题再次失败，已自动重新打开。"
                tasks.append(existing)
                continue
            task = KnowledgeRepairTask(
                business_unit_id=run.business_unit_id,
                knowledge_space_id=case.knowledge_space_id,
                evaluation_run_id=run.id,
                evaluation_case_id=case.id,
                status="OPEN",
                priority="P1" if case.expect_no_grounding else "P2",
                title=title,
                query=case.query,
                expected_titles_json=case.expected_titles_json,
                returned_titles_json=[
                    str(title)
                    for title in cast(
                        list[object],
                        score.get("returned_titles", []),
                    )
                ],
                created_by=run.created_by,
            )
            self.session.add(task)
            tasks.append(task)
        if tasks:
            self.session.commit()
            for task in tasks:
                self.session.refresh(task)
        return tasks

    def create_from_feedback(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None,
        title: str,
        query: str,
        reason_code: str,
        created_by: str,
    ) -> KnowledgeRepairTask:
        normalized_query = normalize_repair_query(query)
        self._lock_dedup_key(
            repair_dedup_key(
                business_unit_id=business_unit_id,
                knowledge_space_id=knowledge_space_id,
                query=normalized_query,
            )
        )
        existing = self._find_reusable(
            business_unit_id=business_unit_id,
            knowledge_space_id=knowledge_space_id,
            normalized_query=normalized_query,
        )
        if existing is not None:
            if existing.status == "CLOSED":
                existing.status = "OPEN"
                existing.resolved_at = None
                existing.resolution_note = "同一问题再次出现，已自动重新打开。"
            existing.query = normalized_query
            if reason_code in {"WRONG_ANSWER", "UNSAFE_ANSWER"}:
                existing.priority = "P1"
            self.session.commit()
            self.session.refresh(existing)
            return existing
        task = KnowledgeRepairTask(
            business_unit_id=business_unit_id,
            knowledge_space_id=knowledge_space_id,
            status="OPEN",
            priority="P1" if reason_code in {"WRONG_ANSWER", "UNSAFE_ANSWER"} else "P2",
            title=title,
            query=normalized_query,
            expected_titles_json=[],
            returned_titles_json=[],
            created_by=created_by,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def _lock_dedup_key(self, key: str) -> None:
        """Serialize repair task creation for the same dedup key.

        Deduplication reads before inserting, so concurrent requests would
        otherwise each miss the existing row and create a duplicate task.
        PostgreSQL advisory locks are transaction scoped and released on
        commit; other dialects fall back to the sequential behavior.
        """

        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(key)))
        )

    def _find_reusable(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None,
        normalized_query: str,
    ) -> KnowledgeRepairTask | None:
        key = repair_dedup_key(
            business_unit_id=business_unit_id,
            knowledge_space_id=knowledge_space_id,
            query=normalized_query,
        )
        space_condition = (
            KnowledgeRepairTask.knowledge_space_id.is_(None)
            if knowledge_space_id is None
            else KnowledgeRepairTask.knowledge_space_id == knowledge_space_id
        )
        candidates = list(
            self.session.scalars(
                select(KnowledgeRepairTask)
                .where(
                    KnowledgeRepairTask.business_unit_id == business_unit_id,
                    space_condition,
                )
                .order_by(KnowledgeRepairTask.created_at.desc())
            ).all()
        )
        for candidate in candidates:
            if (
                repair_dedup_key(
                    business_unit_id=candidate.business_unit_id,
                    knowledge_space_id=candidate.knowledge_space_id,
                    query=normalize_repair_query(candidate.query),
                )
                == key
            ):
                return candidate
        return None

    def list(
        self,
        *,
        business_unit_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> KnowledgeRepairTaskList:
        statement = select(KnowledgeRepairTask).where(
            KnowledgeRepairTask.business_unit_id == business_unit_id
        )
        if status:
            statement = statement.where(KnowledgeRepairTask.status == status)
        tasks = list(
            self.session.scalars(
                statement.order_by(
                    KnowledgeRepairTask.created_at.desc()
                ).limit(max(limit * 10, 500))
            ).all()
        )
        grouped: dict[str, list[KnowledgeRepairTask]] = {}
        for task in tasks:
            normalized = normalize_repair_query(task.query)
            key = repair_dedup_key(
                business_unit_id=task.business_unit_id,
                knowledge_space_id=task.knowledge_space_id,
                query=normalized,
            )
            grouped.setdefault(key, []).append(task)
        status_rank = {"IN_REPAIR": 0, "OPEN": 1, "VERIFIED": 2, "CLOSED": 3}
        task_ids = [task.id for task in tasks]
        feedback_counts: dict[UUID, int] = {}
        if task_ids:
            rows = self.session.execute(
                select(
                    KnowledgeFeedback.repair_task_id,
                    func.count(KnowledgeFeedback.id),
                )
                .where(KnowledgeFeedback.repair_task_id.in_(task_ids))
                .group_by(KnowledgeFeedback.repair_task_id)
            ).all()
            for task_id, count in rows:
                if task_id is not None:
                    feedback_counts[task_id] = int(count)
        selected: list[tuple[KnowledgeRepairTask, int]] = []
        for group in grouped.values():
            canonical = sorted(
                group,
                key=lambda item: (
                    status_rank.get(item.status, 4),
                    -item.updated_at.timestamp(),
                ),
            )[0]
            occurrence_count = sum(
                int(feedback_counts.get(task.id, 0)) for task in group
            )
            selected.append(
                (canonical, occurrence_count or len(group))
            )
        selected.sort(key=lambda item: item[0].updated_at, reverse=True)
        selected = selected[:limit]
        return KnowledgeRepairTaskList(
            items=[
                self.view(task, occurrence_count=occurrence_count)
                for task, occurrence_count in selected
            ],
            total=len(grouped),
        )

    def get(self, task_id: UUID) -> KnowledgeRepairTask:
        task = self.session.get(KnowledgeRepairTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge repair task not found",
                detail=f"Knowledge repair task {task_id} does not exist.",
            )
        return task

    def update(
        self,
        task_id: UUID,
        payload: KnowledgeRepairTaskUpdate,
    ) -> KnowledgeRepairTask:
        task = self.get(task_id)
        if payload.status is not None:
            task.status = payload.status
            task.resolved_at = (
                datetime.now(UTC) if payload.status == "CLOSED" else None
            )
        if payload.priority is not None:
            task.priority = payload.priority
        if payload.assignee_id is not None:
            task.assignee_id = payload.assignee_id
        if payload.resolution_note is not None:
            task.resolution_note = payload.resolution_note
        self.session.commit()
        self.session.refresh(task)
        return task

    def verify(self, task_id: UUID) -> KnowledgeRepairTask:
        from ticket_agent.knowledge.evaluation_service import (
            KnowledgeEvaluationService,
        )
        from ticket_agent.knowledge.schemas import (
            KnowledgeEvaluationDataset,
            KnowledgeEvaluationRunCreate,
        )

        task = self.get(task_id)
        dataset: KnowledgeEvaluationDataset = "TUNING"
        if task.evaluation_run_id is not None:
            source_run = self.session.get(
                KnowledgeEvaluationRun, task.evaluation_run_id
            )
            if source_run is not None:
                dataset = cast(KnowledgeEvaluationDataset, source_run.dataset)
        run = KnowledgeEvaluationService(self.session).run(
            KnowledgeEvaluationRunCreate(
                business_unit_id=task.business_unit_id,
                knowledge_space_id=task.knowledge_space_id,
                dataset=dataset,
            ),
            actor_id="system.knowledge_repair",
        )
        task.status = "VERIFIED" if run.verdict == "PASS" else "IN_REPAIR"
        task.resolution_note = (
            f"回归评测 {run.id} 通过：{run.passed_cases}/{run.case_count}"
            if run.verdict == "PASS"
            else f"回归评测 {run.id} 未通过：{run.failed_cases} 个失败"
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def view(
        self,
        task: KnowledgeRepairTask,
        *,
        occurrence_count: int = 1,
    ) -> KnowledgeRepairTaskView:
        return KnowledgeRepairTaskView(
            id=task.id,
            business_unit_id=task.business_unit_id,
            knowledge_space_id=task.knowledge_space_id,
            evaluation_run_id=task.evaluation_run_id,
            evaluation_case_id=task.evaluation_case_id,
            status=task.status,
            priority=task.priority,
            title=task.title,
            query=normalize_repair_query(task.query),
            expected_titles=task.expected_titles_json,
            returned_titles=task.returned_titles_json,
            assignee_id=task.assignee_id,
            resolution_note=task.resolution_note,
            created_by=task.created_by,
            created_at=task.created_at,
            updated_at=task.updated_at,
            resolved_at=task.resolved_at,
            occurrence_count=occurrence_count,
        )


def normalize_repair_query(query: str) -> str:
    value = query.replace("\r\n", "\n").strip()
    if "当前问题：" in value:
        value = value.rsplit("当前问题：", 1)[-1]
    elif "历史对话：" in value:
        value = value.rsplit("历史对话：", 1)[-1]
    lines: list[str] = []
    for line in value.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue
        if lines and cleaned == lines[-1]:
            continue
        lines.append(cleaned)
    return "\n".join(lines)[:4000]


def repair_dedup_key(
    *,
    business_unit_id: str,
    knowledge_space_id: UUID | None,
    query: str,
) -> str:
    payload = "\x1f".join(
        [
            business_unit_id,
            str(knowledge_space_id or ""),
            normalize_repair_query(query).lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
