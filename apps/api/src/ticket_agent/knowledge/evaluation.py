from collections.abc import Iterable
from dataclasses import dataclass, field

from ticket_agent.knowledge.service import KnowledgeHit


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    business_unit_id: str
    expected_titles: list[str]
    expect_no_grounding: bool = False
    scope: dict[str, str] = field(default_factory=dict)
    dataset: str = "TUNING"
    expected_chunk_ids: list[str] = field(default_factory=list)
    expected_document_ids: list[str] = field(default_factory=list)
    negative_document_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaseScore:
    query: str
    recall_at_k: float
    reciprocal_rank: float
    returned_titles: list[str]
    no_grounding_correct: bool | None
    chunk_recall_at_k: float | None
    chunk_reciprocal_rank: float | None
    returned_chunk_ids: list[str]
    document_recall_at_k: float | None
    document_reciprocal_rank: float | None
    returned_document_ids: list[str]
    context_precision: float | None
    negative_document_hit: bool | None
    passed: bool


def score_evaluation(
    cases: list[EvaluationCase],
    results: list[list[KnowledgeHit]],
    *,
    top_k: int,
) -> dict[str, object]:
    if len(cases) != len(results):
        raise ValueError("cases and results must have the same length")

    scored_cases: list[CaseScore] = []
    for case, hits in zip(cases, results, strict=True):
        top_hits = hits[:top_k]
        returned_titles = [hit.title for hit in top_hits]
        returned_chunk_ids = [str(hit.chunk_id) for hit in top_hits]
        returned_document_ids = _unique(
            str(hit.document_id) for hit in top_hits
        )
        expected_titles = set(case.expected_titles)
        expected_chunks = set(case.expected_chunk_ids)
        expected_documents = set(case.expected_document_ids)
        negative_documents = set(case.negative_document_ids)

        if case.expect_no_grounding:
            no_grounding_correct = not top_hits
            recall = 1.0 if no_grounding_correct else 0.0
            reciprocal_rank = 0.0
        else:
            recall, reciprocal_rank = _recall_and_rank(
                expected_titles,
                returned_titles,
                top_k=top_k,
            )
            no_grounding_correct = None

        chunk_recall: float | None = None
        chunk_rank: float | None = None
        if expected_chunks:
            chunk_recall, chunk_rank = _recall_and_rank(
                expected_chunks,
                returned_chunk_ids,
                top_k=top_k,
            )

        document_recall: float | None = None
        document_rank: float | None = None
        if expected_documents:
            document_recall, document_rank = _recall_and_rank(
                expected_documents,
                returned_document_ids,
                top_k=top_k,
            )

        context_precision: float | None = None
        if (
            not case.expect_no_grounding
            and (expected_chunks or expected_documents)
        ):
            relevant = sum(
                1
                for hit in top_hits
                if str(hit.chunk_id) in expected_chunks
                or str(hit.document_id) in expected_documents
            )
            context_precision = relevant / len(top_hits) if top_hits else 0.0

        negative_hit: bool | None = None
        if negative_documents:
            negative_hit = any(
                str(hit.document_id) in negative_documents for hit in top_hits
            )

        passed = _passed(
            case=case,
            no_grounding_correct=no_grounding_correct,
            recall=recall,
            chunk_recall=chunk_recall,
            document_recall=document_recall,
            negative_hit=negative_hit,
        )
        scored_cases.append(
            CaseScore(
                query=case.query,
                recall_at_k=recall,
                reciprocal_rank=reciprocal_rank,
                returned_titles=returned_titles,
                no_grounding_correct=no_grounding_correct,
                chunk_recall_at_k=chunk_recall,
                chunk_reciprocal_rank=chunk_rank,
                returned_chunk_ids=returned_chunk_ids,
                document_recall_at_k=document_recall,
                document_reciprocal_rank=document_rank,
                returned_document_ids=returned_document_ids,
                context_precision=context_precision,
                negative_document_hit=negative_hit,
                passed=passed,
            )
        )

    no_grounding_scores = [
        score.no_grounding_correct
        for score in scored_cases
        if score.no_grounding_correct is not None
    ]
    positive_scores = [
        score
        for case, score in zip(cases, scored_cases, strict=True)
        if case.expected_titles and not case.expect_no_grounding
    ]
    chunk_scores = [
        score for score in scored_cases if score.chunk_recall_at_k is not None
    ]
    document_scores = [
        score
        for score in scored_cases if score.document_recall_at_k is not None
    ]
    precision_scores = [
        score for score in scored_cases if score.context_precision is not None
    ]
    negative_scores = [
        score
        for score in scored_cases
        if score.negative_document_hit is not None
    ]
    return {
        "case_count": len(scored_cases),
        "passed_cases": sum(1 for score in scored_cases if score.passed),
        "recall_at_k": (
            _mean([score.recall_at_k for score in positive_scores])
            if positive_scores
            else None
        ),
        "mrr": (
            _mean([score.reciprocal_rank for score in positive_scores])
            if positive_scores
            else None
        ),
        "no_grounding_accuracy": (
            _mean([1.0 if value else 0.0 for value in no_grounding_scores])
            if no_grounding_scores
            else None
        ),
        "chunk_recall_at_k": (
            _mean(
                [
                    score.chunk_recall_at_k
                    for score in chunk_scores
                    if score.chunk_recall_at_k is not None
                ]
            )
            if chunk_scores
            else None
        ),
        "chunk_mrr": (
            _mean(
                [
                    score.chunk_reciprocal_rank
                    for score in chunk_scores
                    if score.chunk_reciprocal_rank is not None
                ]
            )
            if chunk_scores
            else None
        ),
        "document_recall_at_k": (
            _mean(
                [
                    score.document_recall_at_k
                    for score in document_scores
                    if score.document_recall_at_k is not None
                ]
            )
            if document_scores
            else None
        ),
        "document_mrr": (
            _mean(
                [
                    score.document_reciprocal_rank
                    for score in document_scores
                    if score.document_reciprocal_rank is not None
                ]
            )
            if document_scores
            else None
        ),
        "context_precision": (
            _mean(
                [
                    score.context_precision
                    for score in precision_scores
                    if score.context_precision is not None
                ]
            )
            if precision_scores
            else None
        ),
        "negative_violation_rate": (
            _mean(
                [
                    1.0 if score.negative_document_hit else 0.0
                    for score in negative_scores
                ]
            )
            if negative_scores
            else None
        ),
        "cases": [
            {
                "query": score.query,
                "passed": score.passed,
                "recall_at_k": score.recall_at_k,
                "reciprocal_rank": score.reciprocal_rank,
                "returned_titles": score.returned_titles,
                "no_grounding_correct": score.no_grounding_correct,
                "chunk_recall_at_k": score.chunk_recall_at_k,
                "chunk_reciprocal_rank": score.chunk_reciprocal_rank,
                "returned_chunk_ids": score.returned_chunk_ids,
                "document_recall_at_k": score.document_recall_at_k,
                "document_reciprocal_rank": score.document_reciprocal_rank,
                "returned_document_ids": score.returned_document_ids,
                "context_precision": score.context_precision,
                "negative_document_hit": score.negative_document_hit,
            }
            for score in scored_cases
        ],
    }


def _recall_and_rank(
    expected: set[str],
    returned: list[str],
    *,
    top_k: int,
) -> tuple[float, float]:
    denominator = min(len(expected), top_k)
    recall = (
        len(expected & set(returned)) / denominator if denominator else 0.0
    )
    first_relevant_rank = next(
        (
            rank
            for rank, value in enumerate(returned, start=1)
            if value in expected
        ),
        None,
    )
    reciprocal_rank = (
        1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
    )
    return recall, reciprocal_rank


def _passed(
    *,
    case: EvaluationCase,
    no_grounding_correct: bool | None,
    recall: float,
    chunk_recall: float | None,
    document_recall: float | None,
    negative_hit: bool | None,
) -> bool:
    if negative_hit:
        return False
    if case.expect_no_grounding:
        return bool(no_grounding_correct)
    checks = []
    if case.expected_titles:
        checks.append(recall >= 1.0)
    if case.expected_chunk_ids:
        checks.append(chunk_recall is not None and chunk_recall >= 1.0)
    if case.expected_document_ids:
        checks.append(
            document_recall is not None and document_recall >= 1.0
        )
    return bool(checks) and all(checks)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
