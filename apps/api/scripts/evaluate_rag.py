#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from ticket_agent.knowledge.evaluation import EvaluationCase, score_evaluation
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate knowledge retrieval quality.")
    parser.add_argument("dataset", type=Path, help="JSONL evaluation dataset")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")

    cases = [
        _parse_case(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with SessionLocal() as session:
        service = KnowledgeService(session)
        results = [
            service.search(
                query=case.query,
                business_unit_id=case.business_unit_id,
                scope=case.scope,
                top_k=args.top_k,
            )
            for case in cases
        ]
    report = score_evaluation(cases, results, top_k=args.top_k)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _parse_case(line: str) -> EvaluationCase:
    payload = json.loads(line)
    return EvaluationCase(
        query=str(payload["query"]),
        business_unit_id=str(payload["business_unit_id"]),
        expected_titles=[
            str(item) for item in payload.get("expected_titles", [])
        ],
        expect_no_grounding=bool(payload.get("expect_no_grounding", False)),
        scope={
            str(key): str(value)
            for key, value in payload.get("scope", {}).items()
        },
        dataset=str(payload.get("dataset") or "TUNING"),
        expected_chunk_ids=[
            str(item) for item in payload.get("expected_chunk_ids", [])
        ],
        expected_document_ids=[
            str(item) for item in payload.get("expected_document_ids", [])
        ],
        negative_document_ids=[
            str(item) for item in payload.get("negative_document_ids", [])
        ],
    )


if __name__ == "__main__":
    main()

