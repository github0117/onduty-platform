#!/usr/bin/env python3
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select

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
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    # 语料不随仓库发布，由 scripts/sync_acceptance_corpus.sh 在 api
    # 容器启动后复制到可写的 /tmp 目录。
    corpus_dir = Path(
        sys.argv[2]
        if len(sys.argv) > 2
        else "/tmp/acceptance-corpus"
    ).resolve()
    tickets = _read_jsonl(corpus_dir / "tickets.jsonl")
    knowledge = _read_jsonl(corpus_dir / "knowledge.jsonl")
    evaluations = _read_jsonl(corpus_dir / "evaluations.jsonl")

    with httpx.Client(base_url=base_url, timeout=60) as client:
        employee = _ensure_employee(client)
        document_titles = _seed_knowledge(client, knowledge)
        case_count = _seed_evaluations(
            client,
            evaluations,
            document_titles=document_titles,
        )
        ticket_count = _seed_tickets(tickets, employee_id=UUID(employee["id"]))
        evaluation = _run_evaluation(client)
    print(
        json.dumps(
            {
                "business_unit_id": BUSINESS_UNIT,
                "tickets": ticket_count,
                "knowledge_documents": len(document_titles),
                "evaluation_cases": case_count,
                "evaluation_run": {
                    "verdict": evaluation.get("verdict"),
                    "case_count": evaluation.get("case_count"),
                    "passed_cases": evaluation.get("passed_cases"),
                    "failed_cases": evaluation.get("failed_cases"),
                    "recall_at_k": evaluation.get("recall_at_k"),
                    "mrr": evaluation.get("mrr"),
                    "no_grounding_accuracy": evaluation.get(
                        "no_grounding_accuracy"
                    ),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


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
) -> dict[str, str]:
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
    titles: dict[str, str] = {}
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
        titles[str(item["id"])] = str(item["title"])
    return titles


def _seed_evaluations(
    client: httpx.Client,
    items: list[dict[str, Any]],
    *,
    document_titles: dict[str, str],
) -> int:
    existing = client.get(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    existing.raise_for_status()
    existing_by_name = {item["name"]: item for item in existing.json()}
    for item in items:
        name = f"验收问题 {item['id']}"
        expected = document_titles.get(str(item.get("expected_document_id") or ""))
        payload = {
            "name": name,
            "query": item["query"],
            "expected_titles": [expected] if expected else [],
            "expect_no_grounding": bool(item["should_refuse"]),
            "scope": {"audience": "support_agent"},
            "enabled": True,
        }
        existing_case = existing_by_name.get(name)
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
        else:
            response = client.patch(
                f"/api/v1/knowledge/evaluation-cases/{existing_case['id']}",
                headers=ADMIN,
                json=payload,
            )
        response.raise_for_status()
    return len(items)


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


def _run_evaluation(client: httpx.Client) -> dict[str, Any]:
    response = client.post(
        "/api/v1/knowledge/evaluation-runs",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_id": None,
            "top_k": 5,
            "min_recall_at_k": 0.5,
            "min_mrr": 0.3,
            "min_no_grounding_accuracy": 0.8,
        },
    )
    response.raise_for_status()
    return response.json()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    main()
