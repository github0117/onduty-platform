from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.evaluation import EvaluationCase, score_evaluation
from ticket_agent.knowledge.models import (
    KnowledgeDocument,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationRun,
    KnowledgeSpace,
    KnowledgeVersion,
)
from ticket_agent.knowledge.repair_service import KnowledgeRepairService
from ticket_agent.knowledge.schemas import (
    KnowledgeEvaluationCaseCreate,
    KnowledgeEvaluationCaseUpdate,
    KnowledgeEvaluationCaseView,
    KnowledgeEvaluationRunCreate,
    KnowledgeEvaluationRunList,
    KnowledgeEvaluationRunView,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.errors import ApiProblem


class KnowledgeEvaluationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_case(
        self,
        payload: KnowledgeEvaluationCaseCreate,
        *,
        actor_id: str,
    ) -> KnowledgeEvaluationCase:
        if not payload.expected_titles and not payload.expect_no_grounding:
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_EXPECTATION_REQUIRED",
                title="Evaluation expectation is missing",
                detail=(
                    "An evaluation case must define expected titles or expect no grounding."
                ),
            )
        self._validate_scope_references(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
        )
        existing = self._find_equivalent_case(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
            query=payload.query,
        )
        if existing is not None:
            existing.name = payload.name.strip()
            existing.expected_titles_json = payload.expected_titles
            existing.expect_no_grounding = payload.expect_no_grounding
            existing.scope_json = payload.scope
            existing.enabled = True
            self.session.commit()
            self.session.refresh(existing)
            return existing
        case = KnowledgeEvaluationCase(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
            name=payload.name.strip(),
            query=payload.query.strip(),
            expected_titles_json=payload.expected_titles,
            expect_no_grounding=payload.expect_no_grounding,
            scope_json=payload.scope,
            enabled=True,
            created_by=actor_id,
        )
        self.session.add(case)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self._find_equivalent_case(
                business_unit_id=payload.business_unit_id,
                knowledge_space_id=payload.knowledge_space_id,
                employee_id=payload.employee_id,
                query=payload.query,
            )
            if existing is None:
                raise
            self.session.refresh(existing)
            return existing
        self.session.refresh(case)
        return case

    def _find_equivalent_case(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None,
        employee_id: UUID | None,
        query: str,
    ) -> KnowledgeEvaluationCase | None:
        statement = select(KnowledgeEvaluationCase).where(
            KnowledgeEvaluationCase.business_unit_id == business_unit_id,
        )
        if knowledge_space_id is None:
            statement = statement.where(
                KnowledgeEvaluationCase.knowledge_space_id.is_(None)
            )
        else:
            statement = statement.where(
                KnowledgeEvaluationCase.knowledge_space_id
                == knowledge_space_id
            )
        if employee_id is None:
            statement = statement.where(
                KnowledgeEvaluationCase.employee_id.is_(None)
            )
        else:
            statement = statement.where(
                KnowledgeEvaluationCase.employee_id == employee_id
            )
        normalized_query = " ".join(query.split()).casefold()
        return next(
            (
                case
                for case in self.session.scalars(statement).all()
                if " ".join(case.query.split()).casefold()
                == normalized_query
            ),
            None,
        )

    def publish_with_gate(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        actor_id: str,
    ) -> KnowledgeVersion:
        document = self.session.get(KnowledgeDocument, document_id)
        if document is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge document not found",
                detail=f"Knowledge document {document_id} does not exist.",
            )
        space = (
            self.session.get(KnowledgeSpace, document.space_id)
            if document.space_id is not None
            else None
        )
        knowledge_service = KnowledgeService(self.session)
        if space is None or not space.evaluation_required:
            return knowledge_service.publish_version(
                document_id,
                version_id,
                actor_id=actor_id,
            )

        previous_versions = list(
            self.session.scalars(
                select(KnowledgeVersion).where(
                    KnowledgeVersion.document_id == document.id,
                    KnowledgeVersion.status == "ACTIVE",
                )
            ).all()
        )
        previous_state = [
            (version.id, version.effective_to) for version in previous_versions
        ]
        previous_current_version_id = document.current_version_id
        previous_document_status = document.status
        try:
            published = knowledge_service.publish_version(
                document_id,
                version_id,
                actor_id=actor_id,
            )
            run = self.run(
                KnowledgeEvaluationRunCreate(
                    business_unit_id=document.business_unit_id,
                    knowledge_space_id=space.id,
                ),
                actor_id=actor_id,
            )
            if run.verdict != "PASS":
                raise ApiProblem(
                    status_code=409,
                    code="KNOWLEDGE_EVALUATION_GATE_FAILED",
                    title="Knowledge evaluation did not pass",
                    detail=(
                        f"Evaluation run {run.id} failed with "
                        f"{run.failed_cases}/{run.case_count} failed cases."
                    ),
                )
            return published
        except Exception:
            self._restore_previous_version(
                document=document,
                candidate_version_id=version_id,
                previous_state=previous_state,
                previous_current_version_id=previous_current_version_id,
                previous_document_status=previous_document_status,
            )
            raise

    def _restore_previous_version(
        self,
        *,
        document: KnowledgeDocument,
        candidate_version_id: UUID,
        previous_state: list[tuple[UUID, datetime | None]],
        previous_current_version_id: UUID | None,
        previous_document_status: str,
    ) -> None:
        self.session.rollback()
        stored_document = self.session.get(KnowledgeDocument, document.id)
        candidate = self.session.get(KnowledgeVersion, candidate_version_id)
        if stored_document is None or candidate is None:
            return
        candidate.status = "DRAFT"
        candidate.published_at = None
        candidate.published_by = None
        for previous_id, effective_to in previous_state:
            stored_previous = self.session.get(KnowledgeVersion, previous_id)
            if stored_previous is not None:
                stored_previous.status = "ACTIVE"
                stored_previous.effective_to = effective_to
        stored_document.current_version_id = previous_current_version_id
        stored_document.status = previous_document_status
        self.session.commit()

    def list_cases(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None = None,
    ) -> list[KnowledgeEvaluationCase]:
        statement = select(KnowledgeEvaluationCase).where(
            KnowledgeEvaluationCase.business_unit_id == business_unit_id
        )
        if knowledge_space_id is not None:
            statement = statement.where(
                KnowledgeEvaluationCase.knowledge_space_id
                == knowledge_space_id
            )
        return list(
            self.session.scalars(
                statement.order_by(KnowledgeEvaluationCase.created_at)
            ).all()
        )

    def get_case(self, case_id: UUID) -> KnowledgeEvaluationCase:
        case = self.session.get(KnowledgeEvaluationCase, case_id)
        if case is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge evaluation case not found",
                detail=f"Knowledge evaluation case {case_id} does not exist.",
            )
        return case

    def update_case(
        self,
        case_id: UUID,
        payload: KnowledgeEvaluationCaseUpdate,
    ) -> KnowledgeEvaluationCase:
        case = self.get_case(case_id)
        if payload.name is not None:
            case.name = payload.name.strip()
        if payload.query is not None:
            case.query = payload.query.strip()
        if payload.expected_titles is not None:
            case.expected_titles_json = payload.expected_titles
        if payload.expect_no_grounding is not None:
            case.expect_no_grounding = payload.expect_no_grounding
        if payload.scope is not None:
            case.scope_json = payload.scope
        if payload.enabled is not None:
            case.enabled = payload.enabled
        if not case.expected_titles_json and not case.expect_no_grounding:
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_EXPECTATION_REQUIRED",
                title="Evaluation expectation is missing",
                detail=(
                    "An evaluation case must define expected titles or expect no grounding."
                ),
            )
        self.session.commit()
        self.session.refresh(case)
        return case

    def run(
        self,
        payload: KnowledgeEvaluationRunCreate,
        *,
        actor_id: str,
    ) -> KnowledgeEvaluationRun:
        if payload.knowledge_space_id is not None:
            space = self.session.get(KnowledgeSpace, payload.knowledge_space_id)
            if space is None or space.business_unit_id != payload.business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="KNOWLEDGE_SPACE_NOT_FOUND",
                    title="Knowledge space not found",
                    detail="The evaluation knowledge space does not exist.",
                )
        cases = self.list_cases(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
        )
        cases = [case for case in cases if case.enabled]
        if not cases:
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_EVALUATION_CASES_EMPTY",
                title="No evaluation cases",
                detail="Create at least one enabled evaluation case before running.",
            )
        thresholds = {
            "min_recall_at_k": payload.min_recall_at_k,
            "min_mrr": payload.min_mrr,
            "min_no_grounding_accuracy": payload.min_no_grounding_accuracy,
        }
        run = KnowledgeEvaluationRun(
            business_unit_id=payload.business_unit_id,
            status="RUNNING",
            verdict="PENDING",
            top_k=payload.top_k,
            case_count=len(cases),
            passed_cases=0,
            failed_cases=0,
            thresholds_json=thresholds,
            results_json=[],
            created_by=actor_id,
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        service = KnowledgeService(self.session)
        evaluation_cases = [
            EvaluationCase(
                query=case.query,
                business_unit_id=case.business_unit_id,
                expected_titles=case.expected_titles_json,
                expect_no_grounding=case.expect_no_grounding,
                scope=case.scope_json,
            )
            for case in cases
        ]
        scored_cases: list[dict[str, Any]] = []
        try:
            results = [
                service.search(
                    query=case.query,
                    business_unit_id=case.business_unit_id,
                    space_id=case.knowledge_space_id,
                    employee_id=case.employee_id,
                    scope=case.scope_json,
                    top_k=payload.top_k,
                    correlation_id=f"knowledge-eval:{run.id}",
                )
                for case in cases
            ]
            report = cast(
                dict[str, Any],
                score_evaluation(
                    evaluation_cases,
                    results,
                    top_k=payload.top_k,
                ),
            )
            scored_cases = cast(list[dict[str, Any]], report["cases"])
            passed_cases = sum(
                float(case["recall_at_k"]) >= 1.0
                for case in scored_cases
            )
            recall = _optional_float(report.get("recall_at_k"))
            mrr = _optional_float(report.get("mrr"))
            no_grounding = _optional_float(report.get("no_grounding_accuracy"))
            verdict = _verdict(
                recall=recall,
                mrr=mrr,
                no_grounding=no_grounding,
                thresholds=thresholds,
            )
            run.status = "SUCCEEDED"
            run.verdict = verdict
            run.passed_cases = passed_cases
            run.failed_cases = len(cases) - passed_cases
            run.recall_at_k = recall
            run.mrr = mrr
            run.no_grounding_accuracy = no_grounding
            run.results_json = scored_cases
            run.error_message = None
        except Exception as exc:
            self.session.rollback()
            stored = self.session.get(KnowledgeEvaluationRun, run.id)
            if stored is None:
                raise
            stored.status = "FAILED"
            stored.verdict = "FAIL"
            stored.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            stored.failed_cases = len(cases)
            run = stored
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        if run.status == "SUCCEEDED" and scored_cases:
            KnowledgeRepairService(
                self.session
            ).create_from_evaluation_failures(
                run=run,
                cases=cases,
                scored_cases=scored_cases,
            )
        self.session.refresh(run)
        return run

    def list_runs(
        self,
        *,
        business_unit_id: str,
        limit: int = 20,
    ) -> KnowledgeEvaluationRunList:
        runs = list(
            self.session.scalars(
                select(KnowledgeEvaluationRun)
                .where(
                    KnowledgeEvaluationRun.business_unit_id
                    == business_unit_id
                )
                .order_by(KnowledgeEvaluationRun.created_at.desc())
                .limit(limit)
            ).all()
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(KnowledgeEvaluationRun)
            .where(
                KnowledgeEvaluationRun.business_unit_id
                == business_unit_id
            )
        ) or 0
        return KnowledgeEvaluationRunList(
            items=[self.run_view(run) for run in runs],
            total=total,
        )

    def get_run(self, run_id: UUID) -> KnowledgeEvaluationRun:
        run = self.session.get(KnowledgeEvaluationRun, run_id)
        if run is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge evaluation run not found",
                detail=f"Knowledge evaluation run {run_id} does not exist.",
            )
        return run

    def case_view(
        self,
        case: KnowledgeEvaluationCase,
    ) -> KnowledgeEvaluationCaseView:
        return KnowledgeEvaluationCaseView(
            id=case.id,
            business_unit_id=case.business_unit_id,
            knowledge_space_id=case.knowledge_space_id,
            employee_id=case.employee_id,
            name=case.name,
            query=case.query,
            expected_titles=case.expected_titles_json,
            expect_no_grounding=case.expect_no_grounding,
            scope=case.scope_json,
            enabled=case.enabled,
            created_by=case.created_by,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    def run_view(
        self,
        run: KnowledgeEvaluationRun,
    ) -> KnowledgeEvaluationRunView:
        return KnowledgeEvaluationRunView(
            id=run.id,
            business_unit_id=run.business_unit_id,
            status=run.status,
            verdict=run.verdict,
            top_k=run.top_k,
            case_count=run.case_count,
            passed_cases=run.passed_cases,
            failed_cases=run.failed_cases,
            recall_at_k=run.recall_at_k,
            mrr=run.mrr,
            no_grounding_accuracy=run.no_grounding_accuracy,
            thresholds=run.thresholds_json,
            results=run.results_json,
            error_message=run.error_message,
            created_by=run.created_by,
            created_at=run.created_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )

    def _validate_scope_references(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None,
        employee_id: UUID | None,
    ) -> None:
        if knowledge_space_id is not None:
            space = self.session.get(KnowledgeSpace, knowledge_space_id)
            if space is None or space.business_unit_id != business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="KNOWLEDGE_SPACE_NOT_FOUND",
                    title="Knowledge space not found",
                    detail="The evaluation knowledge space does not exist.",
                )
        if employee_id is not None:
            employee = self.session.get(DigitalEmployee, employee_id)
            if employee is None or employee.business_unit_id != business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="DIGITAL_EMPLOYEE_NOT_FOUND",
                    title="Digital employee not found",
                    detail="The evaluation employee does not exist.",
                )

def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _verdict(
    *,
    recall: float | None,
    mrr: float | None,
    no_grounding: float | None,
    thresholds: dict[str, float],
) -> str:
    checks = [
        recall is None or recall >= thresholds["min_recall_at_k"],
        mrr is None or mrr >= thresholds["min_mrr"],
        no_grounding is None
        or no_grounding >= thresholds["min_no_grounding_accuracy"],
    ]
    return "PASS" if all(checks) else "FAIL"
