from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.evaluation import EvaluationCase, score_evaluation
from ticket_agent.knowledge.models import (
    KnowledgeChunk,
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
    KnowledgeEvaluationDataset,
    KnowledgeEvaluationPassage,
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
        if not (
            payload.expected_titles
            or payload.expected_chunk_ids
            or payload.expected_passages
            or payload.expected_document_ids
            or payload.expect_no_grounding
        ):
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_EXPECTATION_REQUIRED",
                title="Evaluation expectation is missing",
                detail=(
                    "An evaluation case must define expected titles, chunks, "
                    "passages or document ids, or expect no grounding."
                ),
            )
        self._validate_passage_documents(
            business_unit_id=payload.business_unit_id,
            passages=payload.expected_passages,
        )
        self._validate_scope_references(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
        )
        other_dataset = "HOLDOUT" if payload.dataset == "TUNING" else "TUNING"
        overlap = self._find_equivalent_case(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
            query=payload.query,
            dataset=other_dataset,
        )
        if overlap is not None:
            raise ApiProblem(
                status_code=409,
                code="EVALUATION_QUERY_DATASET_OVERLAP",
                title="Evaluation question used in both datasets",
                detail=(
                    "The same question is already registered in "
                    f"{other_dataset}; tuning and holdout questions must be "
                    "independent."
                ),
            )
        existing = self._find_equivalent_case(
            business_unit_id=payload.business_unit_id,
            knowledge_space_id=payload.knowledge_space_id,
            employee_id=payload.employee_id,
            query=payload.query,
            dataset=payload.dataset,
        )
        if existing is not None:
            if existing.dataset == "HOLDOUT":
                if self._case_matches_payload(existing, payload):
                    return existing
                raise _holdout_immutable()
            existing.name = payload.name.strip()
            existing.expected_titles_json = payload.expected_titles
            existing.expected_chunk_ids_json = _uuid_values(
                payload.expected_chunk_ids
            )
            existing.expected_passages_json = _passage_values(
                payload.expected_passages
            )
            existing.expected_document_ids_json = _uuid_values(
                payload.expected_document_ids
            )
            existing.negative_document_ids_json = _uuid_values(
                payload.negative_document_ids
            )
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
            dataset=payload.dataset,
            expected_titles_json=payload.expected_titles,
            expected_chunk_ids_json=_uuid_values(payload.expected_chunk_ids),
            expected_passages_json=_passage_values(payload.expected_passages),
            expected_document_ids_json=_uuid_values(
                payload.expected_document_ids
            ),
            negative_document_ids_json=_uuid_values(
                payload.negative_document_ids
            ),
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
                dataset=payload.dataset,
            )
            if existing is None:
                raise
            self.session.refresh(existing)
            return existing
        self.session.refresh(case)
        return case

    def _case_matches_payload(
        self,
        case: KnowledgeEvaluationCase,
        payload: KnowledgeEvaluationCaseCreate,
    ) -> bool:
        return (
            case.name == payload.name.strip()
            and case.query == payload.query.strip()
            and case.dataset == payload.dataset
            and case.expected_titles_json == payload.expected_titles
            and case.expected_chunk_ids_json
            == _uuid_values(payload.expected_chunk_ids)
            and case.expected_passages_json
            == _passage_values(payload.expected_passages)
            and case.expected_document_ids_json
            == _uuid_values(payload.expected_document_ids)
            and case.negative_document_ids_json
            == _uuid_values(payload.negative_document_ids)
            and case.expect_no_grounding == payload.expect_no_grounding
            and case.scope_json == payload.scope
        )

    def _find_equivalent_case(
        self,
        *,
        business_unit_id: str,
        knowledge_space_id: UUID | None,
        employee_id: UUID | None,
        query: str,
        dataset: str,
    ) -> KnowledgeEvaluationCase | None:
        statement = select(KnowledgeEvaluationCase).where(
            KnowledgeEvaluationCase.business_unit_id == business_unit_id,
            KnowledgeEvaluationCase.dataset == dataset,
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
            holdout_cases = self.session.scalar(
                select(func.count())
                .select_from(KnowledgeEvaluationCase)
                .where(
                    KnowledgeEvaluationCase.business_unit_id
                    == document.business_unit_id,
                    KnowledgeEvaluationCase.knowledge_space_id == space.id,
                    KnowledgeEvaluationCase.dataset == "HOLDOUT",
                    KnowledgeEvaluationCase.enabled.is_(True),
                )
            )
            if not holdout_cases:
                raise ApiProblem(
                    status_code=409,
                    code="KNOWLEDGE_EVALUATION_HOLDOUT_EMPTY",
                    title="No holdout evaluation cases",
                    detail=(
                        "Publishing requires at least one enabled HOLDOUT "
                        "case; tuning cases are not used for the gate."
                    ),
                )
            run = self.run(
                KnowledgeEvaluationRunCreate(
                    business_unit_id=document.business_unit_id,
                    knowledge_space_id=space.id,
                    dataset="HOLDOUT",
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
        dataset: str | None = "TUNING",
    ) -> list[KnowledgeEvaluationCase]:
        statement = select(KnowledgeEvaluationCase).where(
            KnowledgeEvaluationCase.business_unit_id == business_unit_id
        )
        if knowledge_space_id is not None:
            statement = statement.where(
                KnowledgeEvaluationCase.knowledge_space_id
                == knowledge_space_id
            )
        if dataset is not None:
            statement = statement.where(
                KnowledgeEvaluationCase.dataset == dataset
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
        if case.dataset == "HOLDOUT":
            if payload.model_dump(exclude_unset=True) == {"enabled": True}:
                # Disabling a space also disables its cases. Allow restoring a
                # frozen holdout case without permitting edits or hiding it.
                case.enabled = True
                self.session.commit()
                self.session.refresh(case)
                return case
            raise _holdout_immutable()
        target_dataset = payload.dataset or case.dataset
        query = payload.query.strip() if payload.query is not None else case.query
        other_dataset = (
            "HOLDOUT" if target_dataset == "TUNING" else "TUNING"
        )
        overlap = self._find_equivalent_case(
            business_unit_id=case.business_unit_id,
            knowledge_space_id=case.knowledge_space_id,
            employee_id=case.employee_id,
            query=query,
            dataset=other_dataset,
        )
        if overlap is not None and overlap.id != case.id:
            raise ApiProblem(
                status_code=409,
                code="EVALUATION_QUERY_DATASET_OVERLAP",
                title="Evaluation question used in both datasets",
                detail=(
                    "The same question is already registered in "
                    f"{other_dataset}; tuning and holdout questions must be "
                    "independent."
                ),
            )
        if payload.dataset is not None:
            case.dataset = payload.dataset
        if payload.name is not None:
            case.name = payload.name.strip()
        if payload.query is not None:
            case.query = query
        if payload.expected_titles is not None:
            case.expected_titles_json = payload.expected_titles
        if payload.expected_chunk_ids is not None:
            case.expected_chunk_ids_json = _uuid_values(
                payload.expected_chunk_ids
            )
        if payload.expected_passages is not None:
            self._validate_passage_documents(
                business_unit_id=case.business_unit_id,
                passages=payload.expected_passages,
            )
            case.expected_passages_json = _passage_values(
                payload.expected_passages
            )
        if payload.expected_document_ids is not None:
            case.expected_document_ids_json = _uuid_values(
                payload.expected_document_ids
            )
        if payload.negative_document_ids is not None:
            case.negative_document_ids_json = _uuid_values(
                payload.negative_document_ids
            )
        if payload.expect_no_grounding is not None:
            case.expect_no_grounding = payload.expect_no_grounding
        if payload.scope is not None:
            case.scope_json = payload.scope
        if payload.enabled is not None:
            case.enabled = payload.enabled
        if set(case.expected_document_ids_json) & set(
            case.negative_document_ids_json
        ):
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_NEGATIVE_OVERLAP",
                title="Negative document also expected",
                detail=(
                    "negative_document_ids must not overlap expected_document_ids."
                ),
            )
        if case.expect_no_grounding and (
            case.expected_titles_json
            or case.expected_chunk_ids_json
            or case.expected_passages_json
            or case.expected_document_ids_json
        ):
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_EXPECTATION_CONFLICT",
                title="Conflicting evaluation expectation",
                detail=(
                    "expect_no_grounding cannot be combined with expected matches."
                ),
            )
        if not (
            case.expected_titles_json
            or case.expected_chunk_ids_json
            or case.expected_passages_json
            or case.expected_document_ids_json
            or case.expect_no_grounding
        ):
            raise ApiProblem(
                status_code=422,
                code="EVALUATION_EXPECTATION_REQUIRED",
                title="Evaluation expectation is missing",
                detail=(
                    "An evaluation case must define expected titles, chunks, "
                    "passages or document ids, or expect no grounding."
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
            dataset=payload.dataset,
        )
        cases = [case for case in cases if case.enabled]
        if not cases:
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_EVALUATION_CASES_EMPTY",
                title="No evaluation cases",
                detail=(
                    "Create at least one enabled "
                    f"{payload.dataset} evaluation case before running."
                ),
            )
        thresholds = {
            "min_recall_at_k": payload.min_recall_at_k,
            "min_mrr": payload.min_mrr,
            "min_no_grounding_accuracy": payload.min_no_grounding_accuracy,
        }
        service = KnowledgeService(self.session)
        baseline = {
            "dataset": payload.dataset,
            "top_k": payload.top_k,
            "embedding_model": service.embedding_provider.name,
            "embedding_dimensions": service.settings.embedding_dimensions,
            "chunking_version": service.settings.knowledge_chunking_version,
            "retrieval_mode": service.retrieval_mode,
            "rrf_k": service.settings.knowledge_rrf_k,
            "reranker": service.settings.knowledge_rerank_provider,
            "query_context_enabled": (
                service.settings.knowledge_query_context_enabled
            ),
            "query_rewrite_enabled": (
                service.settings.knowledge_query_rewrite_enabled
            ),
            "thresholds": thresholds,
        }
        run = KnowledgeEvaluationRun(
            business_unit_id=payload.business_unit_id,
            dataset=payload.dataset,
            status="RUNNING",
            verdict="PENDING",
            top_k=payload.top_k,
            case_count=len(cases),
            passed_cases=0,
            failed_cases=0,
            thresholds_json=thresholds,
            baseline_json=baseline,
            results_json=[],
            created_by=actor_id,
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        evaluation_cases, unresolved_passages = build_evaluation_cases(
            self.session, cases
        )
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
            unresolved_count = _mark_unresolved_cases(
                cases=cases,
                scored_cases=scored_cases,
                unresolved_passages=unresolved_passages,
            )
            passed_cases = sum(
                1 for case in scored_cases if case.get("passed") is True
            )
            recall = _optional_float(report.get("recall_at_k"))
            mrr = _optional_float(report.get("mrr"))
            no_grounding = _optional_float(report.get("no_grounding_accuracy"))
            chunk_recall = _optional_float(report.get("chunk_recall_at_k"))
            chunk_mrr = _optional_float(report.get("chunk_mrr"))
            document_recall = _optional_float(
                report.get("document_recall_at_k")
            )
            document_mrr = _optional_float(report.get("document_mrr"))
            context_precision = _optional_float(
                report.get("context_precision")
            )
            negative_violation = _optional_float(
                report.get("negative_violation_rate")
            )
            verdict = _verdict(
                recall=_effective_recall(
                    recall, chunk_recall, document_recall
                ),
                mrr=_effective_recall(mrr, chunk_mrr, document_mrr),
                no_grounding=no_grounding,
                thresholds=thresholds,
            )
            if unresolved_count:
                # An unresolved passage means the case no longer points at any
                # text in the corpus. That is a configuration failure, not a
                # retrieval miss, so the run must not quietly pass.
                verdict = "FAIL"
            run.status = "SUCCEEDED"
            run.verdict = verdict
            run.passed_cases = passed_cases
            run.failed_cases = len(cases) - passed_cases
            run.recall_at_k = recall
            run.mrr = mrr
            run.no_grounding_accuracy = no_grounding
            run.chunk_recall_at_k = chunk_recall
            run.chunk_mrr = chunk_mrr
            run.document_recall_at_k = document_recall
            run.document_mrr = document_mrr
            run.context_precision = context_precision
            run.negative_violation_rate = negative_violation
            run.results_json = scored_cases
            run.error_message = (
                f"{unresolved_count} passage expectation(s) no longer match "
                "any chunk in their document; update the case before trusting "
                "this run."
                if unresolved_count
                else None
            )
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
        dataset: str | None = "TUNING",
        limit: int = 20,
    ) -> KnowledgeEvaluationRunList:
        filters = [
            KnowledgeEvaluationRun.business_unit_id == business_unit_id
        ]
        if dataset is not None:
            filters.append(KnowledgeEvaluationRun.dataset == dataset)
        runs = list(
            self.session.scalars(
                select(KnowledgeEvaluationRun)
                .where(*filters)
                .order_by(KnowledgeEvaluationRun.created_at.desc())
                .limit(limit)
            ).all()
        )
        total = self.session.scalar(
            select(func.count())
            .select_from(KnowledgeEvaluationRun)
            .where(*filters)
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
            dataset=cast(KnowledgeEvaluationDataset, case.dataset),
            expected_titles=case.expected_titles_json,
            expected_chunk_ids=_uuid_list(case.expected_chunk_ids_json),
            expected_passages=_passage_models(case.expected_passages_json),
            expected_document_ids=_uuid_list(
                case.expected_document_ids_json
            ),
            negative_document_ids=_uuid_list(
                case.negative_document_ids_json
            ),
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
        # Context size is derived from the stored per-case results so older
        # runs (written before the column existed) still render sensibly.
        context_chars = [
            float(item["context_chars"])
            for item in run.results_json or []
            if isinstance(item.get("context_chars"), int | float)
        ]
        avg_context_chars = (
            round(sum(context_chars) / len(context_chars), 2)
            if context_chars
            else None
        )
        avg_context_tokens = (
            round(avg_context_chars / 1.6, 2)
            if avg_context_chars is not None
            else None
        )
        return KnowledgeEvaluationRunView(
            id=run.id,
            business_unit_id=run.business_unit_id,
            dataset=cast(KnowledgeEvaluationDataset, run.dataset),
            status=run.status,
            verdict=run.verdict,
            top_k=run.top_k,
            case_count=run.case_count,
            passed_cases=run.passed_cases,
            failed_cases=run.failed_cases,
            recall_at_k=run.recall_at_k,
            mrr=run.mrr,
            no_grounding_accuracy=run.no_grounding_accuracy,
            chunk_recall_at_k=run.chunk_recall_at_k,
            chunk_mrr=run.chunk_mrr,
            document_recall_at_k=run.document_recall_at_k,
            document_mrr=run.document_mrr,
            context_precision=run.context_precision,
            negative_violation_rate=run.negative_violation_rate,
            avg_context_chars=avg_context_chars,
            avg_context_tokens=avg_context_tokens,
            thresholds=run.thresholds_json,
            baseline=run.baseline_json or {},
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

    def _validate_passage_documents(
        self,
        *,
        business_unit_id: str,
        passages: list[KnowledgeEvaluationPassage],
    ) -> None:
        for passage in passages:
            document = self.session.get(KnowledgeDocument, passage.document_id)
            if document is None or document.business_unit_id != business_unit_id:
                raise ApiProblem(
                    status_code=404,
                    code="KNOWLEDGE_DOCUMENT_NOT_FOUND",
                    title="Knowledge document not found",
                    detail=(
                        f"Passage document {passage.document_id} does not "
                        "exist in this business unit."
                    ),
                )


def build_evaluation_cases(
    session: Session,
    rows: list[KnowledgeEvaluationCase],
) -> tuple[list[EvaluationCase], dict[UUID, list[dict[str, str]]]]:
    """Build scoring cases, resolving passage expectations to current chunks.

    Passages take precedence over ``expected_chunk_ids_json`` because they are
    the reindex-safe form: the chunk id is looked up by text every run instead
    of being pinned to a row that a rebuild may delete.

    Returns the cases plus a map of unresolved passages keyed by case id.
    """
    cases: list[EvaluationCase] = []
    unresolved: dict[UUID, list[dict[str, str]]] = {}
    for row in rows:
        passages = _stored_passages(row.expected_passages_json)
        chunk_ids = [str(item) for item in row.expected_chunk_ids_json or []]
        if passages:
            chunk_ids, missing = resolve_passages(
                session,
                business_unit_id=row.business_unit_id,
                passages=passages,
            )
            if missing:
                unresolved[row.id] = missing
        cases.append(
            EvaluationCase(
                query=row.query,
                business_unit_id=row.business_unit_id,
                expected_titles=list(row.expected_titles_json or []),
                expect_no_grounding=row.expect_no_grounding,
                scope=dict(row.scope_json or {}),
                dataset=row.dataset,
                expected_chunk_ids=chunk_ids,
                expected_document_ids=[
                    str(item) for item in row.expected_document_ids_json or []
                ],
                negative_document_ids=[
                    str(item)
                    for item in row.negative_document_ids_json or []
                ],
            )
        )
    return cases, unresolved


def resolve_passages(
    session: Session,
    *,
    business_unit_id: str,
    passages: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Map document + text passages to the chunks of the current version."""
    resolved: list[str] = []
    missing: list[dict[str, str]] = []
    cache: dict[str, tuple[list[tuple[str, str]], str | None]] = {}
    for passage in passages:
        document_id = passage["document_id"]
        text = passage["text"]
        entry = cache.get(document_id)
        if entry is None:
            document = session.get(KnowledgeDocument, UUID(document_id))
            if (
                document is None
                or document.business_unit_id != business_unit_id
                or document.current_version_id is None
            ):
                cache[document_id] = ([], "document_not_indexed")
                entry = cache[document_id]
            else:
                chunk_rows = session.execute(
                    select(KnowledgeChunk.id, KnowledgeChunk.content)
                    .where(
                        KnowledgeChunk.knowledge_version_id
                        == document.current_version_id
                    )
                    .order_by(KnowledgeChunk.ordinal)
                ).all()
                entry = (
                    [
                        (str(chunk_id), _normalize_text(content))
                        for chunk_id, content in chunk_rows
                    ],
                    None,
                )
                cache[document_id] = entry
        chunks, error = entry
        if error is not None:
            missing.append(
                {"document_id": document_id, "text": text, "reason": error}
            )
            continue
        needle = _normalize_text(text)
        match = next(
            (chunk_id for chunk_id, content in chunks if needle in content),
            None,
        )
        if match is None:
            missing.append(
                {
                    "document_id": document_id,
                    "text": text,
                    "reason": "text_not_found",
                }
            )
            continue
        if match not in resolved:
            resolved.append(match)
    return resolved, missing


def _mark_unresolved_cases(
    *,
    cases: list[KnowledgeEvaluationCase],
    scored_cases: list[dict[str, Any]],
    unresolved_passages: dict[UUID, list[dict[str, str]]],
) -> int:
    """Fail cases whose passage text no longer resolves; return how many."""
    if not unresolved_passages:
        return 0
    unresolved_count = 0
    for row, score in zip(cases, scored_cases, strict=True):
        missing = unresolved_passages.get(row.id)
        if not missing:
            continue
        unresolved_count += len(missing)
        score["passed"] = False
        score["unresolved_passages"] = missing
    return unresolved_count


def _stored_passages(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    passages: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        document_id = item.get("document_id")
        text = item.get("text")
        if isinstance(document_id, str) and isinstance(text, str) and text.strip():
            passages.append(
                {"document_id": document_id, "text": text.strip()}
            )
    return passages


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _passage_values(
    passages: list[KnowledgeEvaluationPassage],
) -> list[dict[str, str]]:
    return [
        {"document_id": str(passage.document_id), "text": passage.text}
        for passage in passages
    ]


def _passage_models(raw: object) -> list[KnowledgeEvaluationPassage]:
    return [
        KnowledgeEvaluationPassage(
            document_id=UUID(passage["document_id"]),
            text=passage["text"],
        )
        for passage in _stored_passages(raw)
    ]


def _holdout_immutable() -> ApiProblem:
    return ApiProblem(
        status_code=409,
        code="HOLDOUT_CASE_IMMUTABLE",
        title="Holdout case is immutable",
        detail=(
            "HOLDOUT cases are frozen for gate evaluation. Create a TUNING "
            "case to change expectations."
        ),
    )


def _uuid_values(values: list[UUID]) -> list[str]:
    return [str(value) for value in values]


def _uuid_list(values: list[str]) -> list[UUID]:
    return [UUID(value) for value in values]


def _effective_recall(*values: float | None) -> float | None:
    return next((value for value in values if value is not None), None)


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
