from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["supported", "unsupported", "uncertain"]
_VERDICTS: tuple[Verdict, ...] = ("supported", "unsupported", "uncertain")


@dataclass(frozen=True)
class ClaimEvaluationCase:
    case_id: str
    claim_text: str
    claim_type: str
    sources: list[str]
    expected_verdict: Verdict


@dataclass(frozen=True)
class ClaimPrediction:
    verdict: Verdict
    confidence: float


def evaluate_claim_predictions(
    cases: list[ClaimEvaluationCase],
    predictions: list[ClaimPrediction],
    *,
    abstention_threshold: float = 0.0,
) -> dict[str, object]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    adjusted = [
        ClaimPrediction(
            verdict=(
                "uncertain"
                if prediction.confidence < abstention_threshold
                and prediction.verdict != "uncertain"
                else prediction.verdict
            ),
            confidence=prediction.confidence,
        )
        for prediction in predictions
    ]
    confusion: dict[Verdict, dict[Verdict, int]] = {
        expected: {predicted: 0 for predicted in _VERDICTS}
        for expected in _VERDICTS
    }
    correct = 0
    for case, prediction in zip(cases, adjusted, strict=True):
        confusion[case.expected_verdict][prediction.verdict] += 1
        correct += int(case.expected_verdict == prediction.verdict)

    answered = [
        (case, prediction)
        for case, prediction in zip(cases, adjusted, strict=True)
        if prediction.verdict != "uncertain"
    ]
    selective_correct = sum(
        int(case.expected_verdict == prediction.verdict)
        for case, prediction in answered
    )
    return {
        "case_count": len(cases),
        "accuracy": correct / len(cases) if cases else 0.0,
        "macro_f1": _macro_f1(confusion),
        "coverage": len(answered) / len(cases) if cases else 0.0,
        "selective_accuracy": (
            selective_correct / len(answered) if answered else None
        ),
        "confusion_matrix": confusion,
        "abstention_threshold": abstention_threshold,
    }


def calibrate_abstention_threshold(
    cases: list[ClaimEvaluationCase],
    predictions: list[ClaimPrediction],
    *,
    minimum_coverage: float = 0.5,
) -> dict[str, object]:
    thresholds = [round(index * 0.05, 2) for index in range(20)]
    sweep = [
        evaluate_claim_predictions(
            cases,
            predictions,
            abstention_threshold=threshold,
        )
        for threshold in thresholds
    ]
    eligible = [
        item for item in sweep if _metric(item, "coverage") >= minimum_coverage
    ]
    best = max(
        eligible or sweep,
        key=lambda item: (
            _optional_metric(item, "selective_accuracy") or 0.0,
            _metric(item, "coverage"),
            _metric(item, "accuracy"),
        ),
    )
    return {
        "recommended_threshold": best["abstention_threshold"],
        "minimum_coverage": minimum_coverage,
        "best": best,
        "sweep": sweep,
    }


def _macro_f1(
    confusion: Mapping[Verdict, Mapping[Verdict, int]],
) -> float:
    scores: list[float] = []
    for label in _VERDICTS:
        true_positive = confusion[label][label]
        false_positive = sum(
            confusion[other][label] for other in _VERDICTS if other != label
        )
        false_negative = sum(
            confusion[label][other] for other in _VERDICTS if other != label
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return sum(scores) / len(scores)


def _metric(item: Mapping[str, object], key: str) -> float:
    value = item[key]
    return float(value) if isinstance(value, (int, float)) else 0.0


def _optional_metric(item: Mapping[str, object], key: str) -> float | None:
    value = item[key]
    return float(value) if isinstance(value, (int, float)) else None

