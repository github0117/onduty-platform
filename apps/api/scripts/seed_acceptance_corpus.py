#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, func, select

from ticket_agent.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationRun,
)
from ticket_agent.shared.db import SessionLocal, init_db
from ticket_agent.tickets.models import Ticket

BUSINESS_UNIT = "bu_acceptance"
ADMIN = {
    "X-Actor-Id": "acceptance-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": BUSINESS_UNIT,
}


def main() -> None:
    init_db()
    arguments = [argument for argument in sys.argv[1:] if argument != "--reset"]
    reset_evaluations = len(arguments) != len(sys.argv) - 1
    base_url = arguments[0] if arguments else "http://127.0.0.1:8000"
    # 语料不随仓库发布，由 scripts/sync_acceptance_corpus.sh 在 api
    # 容器启动后复制到可写的 /tmp 目录。
    corpus_dir = Path(
        arguments[1] if len(arguments) > 1 else "/tmp/acceptance-corpus"
    ).resolve()
    if reset_evaluations:
        # 旧的验收案例在数据集拆分迁移后会冻结为 HOLDOUT；重建验收语料时
        # 需要显式清理，否则同一问题无法再作为 TUNING 案例写入。
        _reset_evaluations()
    tickets = _read_jsonl(corpus_dir / "tickets.jsonl")
    knowledge = _read_jsonl(corpus_dir / "knowledge.jsonl")
    tuning_path = corpus_dir / "tuning_evaluations.jsonl"
    if not tuning_path.exists():
        tuning_path = corpus_dir / "evaluations.jsonl"
    tuning = _read_jsonl(tuning_path)
    holdout_path = corpus_dir / "holdout_evaluations.jsonl"
    holdout = _read_jsonl(holdout_path) if holdout_path.exists() else []

    with httpx.Client(base_url=base_url, timeout=60) as client:
        employee = _ensure_employee(client)
        documents = _seed_knowledge(client, knowledge)
        case_count = _seed_evaluations(
            client,
            [*tuning, *holdout],
            documents=documents,
        )
        ticket_count = _seed_tickets(
            tickets, employee_id=UUID(employee["id"])
        )
        tuning_run = _run_evaluation(client, "TUNING")
        holdout_run = _run_evaluation(client, "HOLDOUT")
    print(
        json.dumps(
            {
                "business_unit_id": BUSINESS_UNIT,
                "tickets": ticket_count,
                "knowledge_documents": len(documents),
                "evaluation_cases": case_count,
                "evaluation_run": _run_summary(tuning_run),
                "holdout_evaluation_run": _run_summary(holdout_run),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": run.get("dataset"),
        "verdict": run.get("verdict"),
        "case_count": run.get("case_count"),
        "passed_cases": run.get("passed_cases"),
        "failed_cases": run.get("failed_cases"),
        "recall_at_k": run.get("recall_at_k"),
        "mrr": run.get("mrr"),
        "no_grounding_accuracy": run.get("no_grounding_accuracy"),
        "chunk_recall_at_k": run.get("chunk_recall_at_k"),
        "chunk_mrr": run.get("chunk_mrr"),
        "document_recall_at_k": run.get("document_recall_at_k"),
        "document_mrr": run.get("document_mrr"),
        "context_precision": run.get("context_precision"),
        "negative_violation_rate": run.get("negative_violation_rate"),
    }


def _ensure_employee(client: httpx.Client) -> dict[str, Any]:
    response = client.get(
        "/api/v1/digital-employees",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    for employee in response.json():
        if employee.get("template_code") == "enterprise_service_desk":
            return _ensure_tools(client, employee)
    created = client.post(
        "/api/v1/digital-employees/from-template",
        headers=ADMIN,
        json={
            "name": "验收企业服务员工",
            "template_code": "enterprise_service_desk",
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_ids": [],
            "skill_ids": [],
            "mcp_connector_ids": [],
            "model_profile": {},
            "change_note": "验收语料初始化",
        },
    )
    created.raise_for_status()
    return _ensure_tools(client, created.json())


def _ensure_tools(
    client: httpx.Client,
    employee: dict[str, Any],
) -> dict[str, Any]:
    tools = ["ticket.read", "knowledge.search", "draft.create", "ticket.sync"]
    if set(tools).issubset(set(employee.get("tool_allowlist", []))):
        return employee
    response = client.patch(
        f"/api/v1/digital-employees/{employee['id']}",
        headers=ADMIN,
        json={"tool_allowlist": tools},
    )
    response.raise_for_status()
    return response.json()


def _seed_knowledge(
    client: httpx.Client,
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    documents = client.get(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    documents.raise_for_status()
    by_title = {
        item["title"]: item
        for item in documents.json()
        if item["status"] != "ARCHIVED"
    }
    seeded: dict[str, dict[str, Any]] = {}
    for item in items:
        document = by_title.get(str(item["title"]))
        if document is None:
            response = client.post(
                "/api/v1/knowledge-documents",
                headers=ADMIN,
                json={
                    "business_unit_id": BUSINESS_UNIT,
                    "title": item["title"],
                    "doc_type": item["doc_type"],
                    "owner_id": "acceptance-admin",
                    "scope": item["scope"],
                },
            )
            response.raise_for_status()
            document = response.json()
            by_title[str(item["title"])] = document
        versions = client.get(
            f"/api/v1/knowledge-documents/{document['id']}/versions",
            headers=ADMIN,
        )
        versions.raise_for_status()
        if not any(version["status"] == "ACTIVE" for version in versions.json()):
            draft = client.post(
                f"/api/v1/knowledge-documents/{document['id']}/versions",
                headers=ADMIN,
                json={
                    "version_label": f"acceptance-{item['id']}",
                    "content": item["content"],
                },
            )
            draft.raise_for_status()
            published = client.post(
                (
                    f"/api/v1/knowledge-documents/{document['id']}/versions/"
                    f"{draft.json()['id']}/publish"
                ),
                headers=ADMIN,
                json={"release_note": "模拟验收语料"},
            )
            published.raise_for_status()
        seeded[str(item["id"])] = {
            "title": str(item["title"]),
            "document_id": str(document["id"]),
            "chunk_ids": _document_chunk_ids(str(document["id"])),
        }
    return seeded


def _document_chunk_ids(document_id: str) -> list[str]:
    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, UUID(document_id))
        if document is None or document.current_version_id is None:
            return []
        return [
            str(chunk_id)
            for chunk_id in session.scalars(
                select(KnowledgeChunk.id)
                .where(
                    KnowledgeChunk.knowledge_version_id
                    == document.current_version_id
                )
                .order_by(KnowledgeChunk.ordinal)
            ).all()
        ]


def _seed_evaluations(
    client: httpx.Client,
    items: list[dict[str, Any]],
    *,
    documents: dict[str, dict[str, Any]],
) -> int:
    existing_by_dataset = {
        dataset: _existing_cases(client, dataset)
        for dataset in ("TUNING", "HOLDOUT")
    }
    for item in items:
        dataset = str(item.get("dataset") or "TUNING")
        name = f"验收问题 {item['id']}"
        expected = documents.get(str(item.get("expected_document_id") or ""))
        payload = {
            "name": name,
            "query": item["query"],
            "dataset": dataset,
            "expected_titles": [expected["title"]] if expected else [],
            "expected_document_ids": (
                [expected["document_id"]] if expected else []
            ),
            "expected_chunk_ids": (
                expected["chunk_ids"][:1]
                if expected and item.get("expect_chunk")
                else []
            ),
            "expect_no_grounding": bool(item["should_refuse"]),
            "scope": {"audience": "support_agent"},
            "enabled": True,
        }
        existing_case = existing_by_dataset[dataset].get(name)
        if existing_case is None:
            response = client.post(
                "/api/v1/knowledge/evaluation-cases",
                headers=ADMIN,
                json={
                    "business_unit_id": BUSINESS_UNIT,
                    "knowledge_space_id": None,
                    "employee_id": None,
                    **payload,
                },
            )
        elif dataset == "HOLDOUT":
            # Holdout cases are immutable; a re-seed keeps the frozen case.
            continue
        else:
            response = client.patch(
                f"/api/v1/knowledge/evaluation-cases/{existing_case['id']}",
                headers=ADMIN,
                json=payload,
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{response.request.method} {response.request.url} "
                f"returned {response.status_code}: {response.text}"
            )
    return len(items)


def _existing_cases(
    client: httpx.Client,
    dataset: str,
) -> dict[str, dict[str, Any]]:
    response = client.get(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT, "dataset": dataset},
    )
    response.raise_for_status()
    return {item["name"]: item for item in response.json()}


def _seed_tickets(
    items: list[dict[str, Any]],
    *,
    employee_id: UUID,
) -> int:
    with SessionLocal() as session:
        for item in items:
            external_id = str(item["id"])
            existing = session.scalar(
                select(Ticket).where(
                    Ticket.source_system == "acceptance_corpus",
                    Ticket.source_ticket_id == external_id,
                )
            )
            if existing is not None:
                continue
            risk = str(item["risk_level"])
            needs_human = risk in {"R2", "R3"}
            session.add(
                Ticket(
                    business_unit_id=BUSINESS_UNIT,
                    employee_id=employee_id,
                    source_system="acceptance_corpus",
                    source_ticket_id=external_id,
                    source_channel="acceptance_simulation",
                    idempotency_key=f"acceptance-corpus:{external_id}",
                    request_hash=hashlib.sha256(
                        external_id.encode("utf-8")
                    ).hexdigest(),
                    requester_ref=f"acceptance-user-{external_id}",
                    customer_tier="standard",
                    subject=str(item["subject"]),
                    body=str(item["body"]),
                    status="WAITING_HUMAN" if needs_human else "WAITING_USER",
                    workflow_state="NEEDS_HUMAN" if needs_human else "PENDING_REVIEW",
                    category_primary=str(item["category_primary"]),
                    category_secondary="acceptance_corpus",
                    confidence=0.9,
                    priority="P0" if risk == "R3" else "P1" if risk == "R2" else "P2",
                    risk_level=risk,
                    queue_id="MANUAL_TRIAGE" if needs_human else "ENTERPRISE_SERVICE_DESK",
                    needs_human=needs_human,
                    human_reason="HIGH_RISK_TOPIC" if needs_human else None,
                    external_metadata={
                        "scenario": item["scenario"],
                        "corpus": "acceptance",
                    },
                )
            )
        session.commit()
        return int(
            session.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(
                    Ticket.business_unit_id == BUSINESS_UNIT,
                    Ticket.source_system == "acceptance_corpus",
                )
            )
            or 0
        )


def _run_evaluation(
    client: httpx.Client,
    dataset: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/knowledge/evaluation-runs",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_id": None,
            "dataset": dataset,
            "top_k": 5,
            "min_recall_at_k": 0.5,
            "min_mrr": 0.3,
            "min_no_grounding_accuracy": 0.8,
        },
    )
    response.raise_for_status()
    return response.json()


def _reset_evaluations() -> None:
    with SessionLocal() as session:
        session.execute(
            delete(KnowledgeEvaluationRun).where(
                KnowledgeEvaluationRun.business_unit_id == BUSINESS_UNIT
            )
        )
        session.execute(
            delete(KnowledgeEvaluationCase).where(
                KnowledgeEvaluationCase.business_unit_id == BUSINESS_UNIT
            )
        )
        session.commit()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    main()
