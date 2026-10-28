#!/usr/bin/env python3
"""Seed the public real-question corpus into the running stack.

The corpus comes from ``fetch_public_eval_corpus.py``. Each Q&A pair becomes
one knowledge document (title is deliberately neutral, so the query cannot
match the title) and one evaluation case with the answer document as ground
truth. Cases keep their TUNING/HOLDOUT dataset label.
"""

import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select

from ticket_agent.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEvaluationCase,
)
from ticket_agent.shared.db import SessionLocal, init_db

BUSINESS_UNIT = "bu_public_eval"
SPACE_CODE = "public_hr_eval"
SPACE_NAME = "公共人社政策问答基准"
PUBLIC_SCOPE = {"corpus": "public_hr"}
ADMIN = {
    "X-Actor-Id": "acceptance-admin",
    "X-Actor-Role": "admin",
    "X-Business-Unit-Id": BUSINESS_UNIT,
}


def main() -> None:
    init_db()
    arguments = [item for item in sys.argv[1:] if item != "--reset"]
    reset = len(arguments) != len(sys.argv) - 1
    base_url = arguments[0] if arguments else "http://127.0.0.1:8000"
    corpus_dir = Path(arguments[1] if len(arguments) > 1 else "/tmp/public-corpus").resolve()
    items = _read_jsonl(corpus_dir / "public_hr_eval.jsonl")

    with httpx.Client(base_url=base_url, timeout=120) as client:
        space = _ensure_space(client)
        if reset:
            _reset_public_space(str(space["id"]))
        cases = _seed_documents_and_cases(client, space, items)
    print(
        json.dumps(
            {
                "business_unit_id": BUSINESS_UNIT,
                "space_id": space["id"],
                "space_code": SPACE_CODE,
                "documents": len(items),
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _ensure_space(client: httpx.Client) -> dict[str, Any]:
    response = client.get(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        params={"business_unit_id": BUSINESS_UNIT},
    )
    response.raise_for_status()
    for space in response.json():
        if space.get("code") == SPACE_CODE:
            if space.get("status") != "ACTIVE":
                patched = client.patch(
                    f"/api/v1/knowledge-spaces/{space['id']}",
                    headers=ADMIN,
                    json={"status": "ACTIVE"},
                )
                patched.raise_for_status()
                return patched.json()
            return space
    created = client.post(
        "/api/v1/knowledge-spaces",
        headers=ADMIN,
        json={
            "business_unit_id": BUSINESS_UNIT,
            "code": SPACE_CODE,
            "name": SPACE_NAME,
            "description": ("公开政府人社政策问答语料，用于真实查询检索基线；不是企业内部工单。"),
            "domain": "general",
            "owner_id": "acceptance-admin",
        },
    )
    created.raise_for_status()
    return created.json()


def _seed_documents_and_cases(
    client: httpx.Client,
    space: dict[str, Any],
    items: list[dict[str, Any]],
) -> int:
    space_id = str(space["id"])
    documents = client.get(
        "/api/v1/knowledge-documents",
        headers=ADMIN,
        params={
            "business_unit_id": BUSINESS_UNIT,
            "space_id": space_id,
        },
    )
    documents.raise_for_status()
    by_title = {item["title"]: item for item in documents.json()}
    existing_cases = _existing_cases(client, space_id)
    created_cases = 0

    for item in items:
        title = f"{item['id']} 人社政策问答"
        document = by_title.get(title)
        if document is None:
            created = client.post(
                "/api/v1/knowledge-documents",
                headers=ADMIN,
                json={
                    "business_unit_id": BUSINESS_UNIT,
                    "space_id": space_id,
                    "title": title,
                    "doc_type": "FAQ",
                    "owner_id": "acceptance-admin",
                    "scope": PUBLIC_SCOPE,
                },
            )
            created.raise_for_status()
            document = created.json()
            by_title[title] = document
        if document.get("scope") != PUBLIC_SCOPE:
            patched = client.patch(
                f"/api/v1/knowledge-documents/{document['id']}",
                headers=ADMIN,
                json={"scope": PUBLIC_SCOPE},
            )
            patched.raise_for_status()
            document = patched.json()
        chunk_ids = _publish_if_needed(client, str(document["id"]), str(item["answer"]))
        if not chunk_ids:
            raise RuntimeError(f"document {title} has no chunks")
        case_name = f"公共问答 {item['id']}"
        payload = {
            "name": case_name,
            "query": item["question"],
            "dataset": item["dataset"],
            "expected_titles": [],
            "expected_chunk_ids": chunk_ids,
            "expected_document_ids": [str(document["id"])],
            "expect_no_grounding": False,
            "scope": PUBLIC_SCOPE,
            "enabled": True,
        }
        existing = existing_cases.get((item["dataset"], item["question"]))
        if existing is not None:
            if item["dataset"] == "HOLDOUT":
                continue
            response = client.patch(
                f"/api/v1/knowledge/evaluation-cases/{existing['id']}",
                headers=ADMIN,
                json=payload,
            )
        else:
            response = client.post(
                "/api/v1/knowledge/evaluation-cases",
                headers=ADMIN,
                json={
                    "business_unit_id": BUSINESS_UNIT,
                    "knowledge_space_id": space_id,
                    "employee_id": None,
                    **payload,
                },
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"{response.request.method} {response.request.url} "
                f"returned {response.status_code}: {response.text}"
            )
        created_cases += 1
    return created_cases


def _publish_if_needed(
    client: httpx.Client,
    document_id: str,
    answer: str,
) -> list[str]:
    versions = client.get(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN,
    )
    versions.raise_for_status()
    active = [version for version in versions.json() if version["status"] == "ACTIVE"]
    if active:
        return _document_chunk_ids(document_id)
    draft = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=ADMIN,
        json={
            "version_label": f"public-{document_id[-8:]}",
            "content": answer,
        },
    )
    draft.raise_for_status()
    published = client.post(
        (f"/api/v1/knowledge-documents/{document_id}/versions/{draft.json()['id']}/publish"),
        headers=ADMIN,
        json={"release_note": "公开人社政策问答语料"},
    )
    published.raise_for_status()
    return _document_chunk_ids(document_id)


def _document_chunk_ids(document_id: str) -> list[str]:
    with SessionLocal() as session:
        document = session.get(KnowledgeDocument, UUID(document_id))
        if document is None or document.current_version_id is None:
            return []
        return [
            str(chunk_id)
            for chunk_id in session.scalars(
                select(KnowledgeChunk.id)
                .where(KnowledgeChunk.knowledge_version_id == document.current_version_id)
                .order_by(KnowledgeChunk.ordinal)
            ).all()
        ]


def _existing_cases(
    client: httpx.Client,
    space_id: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    response = client.get(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN,
        params={
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_id": space_id,
            "dataset": "TUNING",
        },
    )
    response.raise_for_status()
    result = {("TUNING", item["query"]): item for item in response.json()}
    holdout = client.get(
        "/api/v1/knowledge/evaluation-cases",
        headers=ADMIN,
        params={
            "business_unit_id": BUSINESS_UNIT,
            "knowledge_space_id": space_id,
            "dataset": "HOLDOUT",
        },
    )
    holdout.raise_for_status()
    for item in holdout.json():
        result[("HOLDOUT", item["query"])] = item
    return result


def _reset_public_space(space_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            delete(KnowledgeEvaluationCase).where(
                KnowledgeEvaluationCase.business_unit_id == BUSINESS_UNIT,
                KnowledgeEvaluationCase.knowledge_space_id == UUID(space_id),
            )
        )
        session.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.business_unit_id == BUSINESS_UNIT,
                KnowledgeDocument.space_id == UUID(space_id),
            )
        )
        session.commit()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


if __name__ == "__main__":
    main()
