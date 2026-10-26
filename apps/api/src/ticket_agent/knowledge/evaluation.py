from dataclasses import dataclass, field

from ticket_agent.knowledge.service import KnowledgeHit


@dataclass(frozen=True)
class EvaluationCase:
    query: str
    business_unit_id: str
    expected_titles: list[str]
    expect_no_grounding: bool = False
    scope: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseScore:
    query: str
    recall_at_k: float
    reciprocal_rank: float
    returned_titles: list[str]
    no_grounding_correct: bool | None


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
        returned_titles = [hit.title for hit in hits[:top_k]]
        expected = set(case.expected_titles)
        if case.expect_no_grounding or not expected:
            no_grounding_correct = not returned_titles
            recall = 1.0 if no_grounding_correct else 0.0
            reciprocal_rank = 0.0
        else:
            denominator = min(len(expected), top_k)
            recall = (
                len(expected & set(returned_titles)) / denominator if denominator else 0.0
            )
            first_relevant_rank = next(
                (
                    rank
                    for rank, title in enumerate(returned_titles, start=1)
                    if title in expected
                ),
                None,
            )
            reciprocal_rank = (
                1.0 / first_relevant_rank if first_relevant_rank is not None else 0.0
            )
            no_grounding_correct = None
        scored_cases.append(
            CaseScore(
                query=case.query,
                recall_at_k=recall,
                reciprocal_rank=reciprocal_rank,
                returned_titles=returned_titles,
                no_grounding_correct=no_grounding_correct,
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
    return {
        "case_count": len(scored_cases),
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
        "cases": [
            {
                "query": score.query,
                "recall_at_k": score.recall_at_k,
                "reciprocal_rank": score.reciprocal_rank,
                "returned_titles": score.returned_titles,
                "no_grounding_correct": score.no_grounding_correct,
            }
            for score in scored_cases
        ],
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

