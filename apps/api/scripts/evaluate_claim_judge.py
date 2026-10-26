#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from ticket_agent.knowledge.claim_evaluation import (
    ClaimEvaluationCase,
    ClaimPrediction,
    calibrate_abstention_threshold,
    evaluate_claim_predictions,
)
from ticket_agent.knowledge.claim_verifier import (
    ClaimToVerify,
    HeuristicClaimVerifier,
    get_claim_verifier,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a claim verification provider.")
    parser.add_argument("dataset", type=Path, help="JSONL claim evaluation dataset")
    parser.add_argument(
        "--provider",
        choices=("local", "configured"),
        default="local",
    )
    parser.add_argument("--min-coverage", type=float, default=0.5)
    parser.add_argument("--include-sweep", action="store_true")
    args = parser.parse_args()

    cases = [
        _parse_case(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    verifier = (
        HeuristicClaimVerifier()
        if args.provider == "local"
        else get_claim_verifier()
    )
    if verifier is None:
        parser.error("CLAIM_VERIFIER_PROVIDER is not configured")
    verifications = verifier.verify(
        [
            ClaimToVerify(
                claim_index=index,
                text=case.claim_text,
                claim_type=case.claim_type,
                sources=case.sources,
            )
            for index, case in enumerate(cases)
        ]
    )
    by_index = {item.claim_index: item for item in verifications}
    predictions = [
        ClaimPrediction(
            verdict=by_index[index].verdict,
            confidence=by_index[index].confidence,
        )
        for index in range(len(cases))
    ]

    calibration = calibrate_abstention_threshold(
        cases,
        predictions,
        minimum_coverage=args.min_coverage,
    )
    if not args.include_sweep:
        calibration.pop("sweep", None)
    report = {
        "provider": verifier.name,
        "evaluation": evaluate_claim_predictions(cases, predictions),
        "calibration": calibration,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _parse_case(line: str) -> ClaimEvaluationCase:
    payload = json.loads(line)
    return ClaimEvaluationCase(
        case_id=str(payload["case_id"]),
        claim_text=str(payload["claim_text"]),
        claim_type=str(payload.get("claim_type", "policy")),
        sources=[str(item) for item in payload["sources"]],
        expected_verdict=str(payload["expected_verdict"]),  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main()

