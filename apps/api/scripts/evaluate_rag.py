#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from ticket_agent.knowledge.evaluation import (
    EvaluationCase,
    score_evaluation,
    threshold_failures,
)
from ticket_agent.knowledge.evaluation_service import (
    KnowledgeEvaluationService,
    build_evaluation_cases,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate knowledge retrieval quality.")
    parser.add_argument(
        "dataset",
        type=Path,
        nargs="?",
        help="JSONL evaluation dataset (omit when using --business-unit)",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--business-unit",
        help="Load cases from the database for this business unit instead of JSONL.",
    )
    parser.add_argument(
        "--dataset-name",
        choices=["TUNING", "HOLDOUT"],
        default="HOLDOUT",
        help="Dataset to load in --business-unit mode.",
    )
    parser.add_argument("--space-id", type=UUID)
    parser.add_argument("--min-recall-at-k", type=float)
    parser.add_argument("--min-chunk-recall-at-k", type=float)
    parser.add_argument("--min-document-recall-at-k", type=float)
    parser.add_argument("--min-mrr", type=float)
    parser.add_argument("--min-chunk-mrr", type=float)
    parser.add_argument("--min-document-mrr", type=float)
    parser.add_argument("--min-context-precision", type=float)
    parser.add_argument("--min-no-grounding-accuracy", type=float)
    parser.add_argument("--max-negative-violation-rate", type=float)
    parser.add_argument(
        "--max-unresolved-passages",
        type=int,
        default=0,
        help="Fail when passage expectations no longer resolve (default 0).",
    )
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    if args.business_unit is None and args.dataset is None:
        parser.error("provide a JSONL dataset or --business-unit")

    with SessionLocal() as session:
        service = KnowledgeService(session)
        if args.business_unit is not None:
            entries, unresolved_passages = _cases_from_database(
                session,
                business_unit_id=args.business_unit,
                knowledge_space_id=args.space_id,
                dataset=args.dataset_name,
            )
        else:
            entries = [
                (_parse_case(line), args.space_id, None)
                for line in args.dataset.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            unresolved_passages = 0
        results = [
            service.search(
                query=case.query,
                business_unit_id=case.business_unit_id,
                space_id=space_id,
                employee_id=employee_id,
                scope=case.scope,
                top_k=args.top_k,
            )
            for case, space_id, employee_id in entries
        ]
    report = score_evaluation(
        [case for case, _space_id, _employee_id in entries],
        results,
        top_k=args.top_k,
    )
    report["unresolved_passage_count"] = unresolved_passages
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if unresolved_passages > args.max_unresolved_passages:
        print(
            "threshold failure: unresolved_passage_count "
            f"{unresolved_passages} > maximum {args.max_unresolved_passages}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    minimums = {
        key: value
        for key, value in {
            "recall_at_k": args.min_recall_at_k,
            "chunk_recall_at_k": args.min_chunk_recall_at_k,
            "document_recall_at_k": args.min_document_recall_at_k,
            "mrr": args.min_mrr,
            "chunk_mrr": args.min_chunk_mrr,
            "document_mrr": args.min_document_mrr,
            "context_precision": args.min_context_precision,
            "no_grounding_accuracy": args.min_no_grounding_accuracy,
        }.items()
        if value is not None
    }
    maximums = (
        {"negative_violation_rate": args.max_negative_violation_rate}
        if args.max_negative_violation_rate is not None
        else {}
    )
    failures = threshold_failures(
        report,
        minimums=minimums,
        maximums=maximums,
    )
    if failures:
        for failure in failures:
            print(f"threshold failure: {failure}", file=sys.stderr)
        raise SystemExit(1)


def _cases_from_database(
    session: Session,
    *,
    business_unit_id: str,
    knowledge_space_id: UUID | None,
    dataset: str,
) -> tuple[
    list[tuple[EvaluationCase, UUID | None, UUID | None]],
    int,
]:
    rows = [
        row
        for row in KnowledgeEvaluationService(session).list_cases(
            business_unit_id=business_unit_id,
            knowledge_space_id=knowledge_space_id,
            dataset=dataset,
        )
        if row.enabled
    ]
    cases, unresolved = build_evaluation_cases(session, rows)
    entries = [
        (case, row.knowledge_space_id, row.employee_id)
        for case, row in zip(cases, rows, strict=True)
    ]
    return entries, sum(len(items) for items in unresolved.values())


def _parse_case(line: str) -> EvaluationCase:
    payload = json.loads(line)
    expected_document_ids = payload.get("expected_document_ids")
    if expected_document_ids is None and payload.get("expected_document_id"):
        expected_document_ids = [payload["expected_document_id"]]
    return EvaluationCase(
        query=str(payload["query"]),
        business_unit_id=str(payload["business_unit_id"]),
        expected_titles=[
            str(item) for item in payload.get("expected_titles", [])
        ],
        expect_no_grounding=bool(
            payload.get(
                "expect_no_grounding",
                payload.get("should_refuse", False),
            )
        ),
        scope={
            str(key): str(value)
            for key, value in payload.get("scope", {}).items()
        },
        dataset=str(payload.get("dataset") or "TUNING"),
        expected_chunk_ids=[
            str(item) for item in payload.get("expected_chunk_ids", [])
        ],
        expected_document_ids=[
            str(item) for item in expected_document_ids or []
        ],
        negative_document_ids=[
            str(item) for item in payload.get("negative_document_ids", [])
        ],
    )


if __name__ == "__main__":
    main()
