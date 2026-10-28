from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ticket_agent.shared.db import SessionLocal
from ticket_agent.tickets.models import AnswerDraft, AnswerQualityEvaluation, Ticket

OPERATOR = {
    "X-Actor-Id": "knowledge-operator-quality",
    "X-Actor-Role": "knowledge_operator",
    "X-Business-Unit-Id": "bu_demo",
}
SUPERVISOR = {
    "X-Actor-Id": "supervisor-quality",
    "X-Actor-Role": "supervisor",
    "X-Business-Unit-Id": "bu_demo",
}
AUDITOR = {
    "X-Actor-Id": "auditor-quality",
    "X-Actor-Role": "auditor",
    "X-Business-Unit-Id": "bu_demo",
}
AGENT = {
    "X-Actor-Id": "agent-quality",
    "X-Actor-Role": "agent",
    "X-Business-Unit-Id": "bu_demo",
}


def _adopted_draft(
    session,
    *,
    status: str = "ACCEPTED",
    business_unit_id: str = "bu_demo",
    created_at: datetime | None = None,
    text: str = "已采纳的客服草稿",
) -> AnswerDraft:
    ticket = Ticket(
        business_unit_id=business_unit_id,
        source_system="quality_test",
        source_ticket_id=f"QA-{uuid4()}",
        source_channel="web_form",
        idempotency_key=f"answer-quality-{uuid4()}",
        request_hash="0" * 64,
        requester_ref="quality-customer",
        subject="答案质量抽检工单",
        body="用于抽检回答质量。",
        created_at=created_at or datetime.now(UTC),
    )
    session.add(ticket)
    session.flush()
    draft = AnswerDraft(
        ticket_id=ticket.id,
        text=text,
        status=status,
        grounding_status="GROUNDED",
        created_at=created_at or datetime.now(UTC),
    )
    session.add(draft)
    session.flush()
    return draft


def test_samples_exclude_reviewed_pending_and_old_drafts(client: TestClient) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        oldest = _adopted_draft(session, created_at=now - timedelta(days=2), text="旧草稿")
        _adopted_draft(
            session,
            status="EDITED_AND_ACCEPTED",
            created_at=now - timedelta(days=1),
            text="改后草稿",
        )
        _adopted_draft(session, text="新草稿")
        _adopted_draft(session, status="NEEDS_REVIEW", text="待审核草稿")
        _adopted_draft(session, status="REJECTED", text="驳回草稿")
        _adopted_draft(
            session,
            created_at=now - timedelta(days=40),
            text="窗口外草稿",
        )
        _adopted_draft(
            session,
            business_unit_id="bu_other",
            text="其他业务单元草稿",
        )
        session.commit()
        oldest_id = str(oldest.id)

    response = client.get(
        "/api/v1/knowledge/answer-evaluations/samples"
        "?business_unit_id=bu_demo&days=30&limit=10",
        headers=OPERATOR,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pending_total"] == 3
    assert [item["draft_text"] for item in payload["items"]] == [
        "旧草稿",
        "改后草稿",
        "新草稿",
    ]
    assert payload["items"][0]["draft_id"] == oldest_id
    assert payload["items"][0]["ticket_subject"] == "答案质量抽检工单"


def test_record_upsert_summary_and_queue_progress(client: TestClient) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        _adopted_draft(session, created_at=now - timedelta(days=10))
        _adopted_draft(session)
        _adopted_draft(session)
        session.commit()

    samples = client.get(
        "/api/v1/knowledge/answer-evaluations/samples"
        "?business_unit_id=bu_demo&days=30",
        headers=OPERATOR,
    ).json()
    assert samples["pending_total"] == 3
    draft_id = samples["items"][-1]["draft_id"]

    created = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": draft_id,
            "verdict": "CORRECT",
        },
    )
    assert created.status_code == 200, created.text
    created_payload = created.json()
    assert created_payload["verdict"] == "CORRECT"
    assert created_payload["hallucinated"] is False
    assert created_payload["evaluator_ref"] == "knowledge-operator-quality"

    summary = client.get(
        "/api/v1/knowledge/answer-evaluations/summary"
        "?business_unit_id=bu_demo&days=30",
        headers=OPERATOR,
    ).json()
    assert summary["adopted_total"] == 3
    assert summary["evaluated_total"] == 1
    assert summary["verdict_counts"] == {"CORRECT": 1}
    assert summary["coverage_rate"] == pytest.approx(0.3333)
    assert summary["correctness_rate"] == 1.0
    assert summary["hallucination_rate"] == 0.0

    replaced = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": draft_id,
            "verdict": "PARTIAL",
            "hallucinated": True,
            "note": "引用了一处不存在的规定",
        },
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == created_payload["id"]
    assert replaced.json()["verdict"] == "PARTIAL"
    assert replaced.json()["hallucinated"] is True
    assert replaced.json()["note"] == "引用了一处不存在的规定"

    after = client.get(
        "/api/v1/knowledge/answer-evaluations/summary"
        "?business_unit_id=bu_demo&days=30",
        headers=OPERATOR,
    ).json()
    assert after["evaluated_total"] == 1
    assert after["verdict_counts"] == {"PARTIAL": 1}
    assert after["correctness_rate"] == 0.5
    assert after["hallucination_rate"] == 1.0

    remaining = client.get(
        "/api/v1/knowledge/answer-evaluations/samples"
        "?business_unit_id=bu_demo&days=30",
        headers=OPERATOR,
    ).json()
    assert remaining["pending_total"] == 2
    assert draft_id not in [item["draft_id"] for item in remaining["items"]]

    weekly = client.get(
        "/api/v1/knowledge/answer-evaluations/summary"
        "?business_unit_id=bu_demo&days=7",
        headers=OPERATOR,
    ).json()
    assert weekly["adopted_total"] == 2
    assert weekly["evaluated_total"] == 1


def test_record_rejects_invalid_drafts_and_windows(client: TestClient) -> None:
    with SessionLocal() as session:
        pending = _adopted_draft(session, status="NEEDS_REVIEW")
        other_unit = _adopted_draft(session, business_unit_id="bu_other")
        session.commit()
        pending_id = str(pending.id)
        other_id = str(other_unit.id)

    invalid_verdict = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": pending_id,
            "verdict": "GREAT",
        },
    )
    assert invalid_verdict.status_code == 422

    not_adopted = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": pending_id,
            "verdict": "CORRECT",
        },
    )
    assert not_adopted.status_code == 409
    assert not_adopted.json()["code"] == "ANSWER_DRAFT_NOT_ADOPTED"

    missing = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": str(uuid4()),
            "verdict": "CORRECT",
        },
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "ANSWER_DRAFT_NOT_FOUND"

    cross_unit_draft = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_demo",
            "draft_id": other_id,
            "verdict": "CORRECT",
        },
    )
    assert cross_unit_draft.status_code == 404
    assert cross_unit_draft.json()["code"] == "ANSWER_DRAFT_NOT_FOUND"

    cross_unit_request = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={
            "business_unit_id": "bu_other",
            "draft_id": other_id,
            "verdict": "CORRECT",
        },
    )
    assert cross_unit_request.status_code == 403
    assert cross_unit_request.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"

    for days in ("0", "91"):
        bad_window = client.get(
            f"/api/v1/knowledge/answer-evaluations/summary"
            f"?business_unit_id=bu_demo&days={days}",
            headers=OPERATOR,
        )
        assert bad_window.status_code == 422

    too_many = client.get(
        "/api/v1/knowledge/answer-evaluations/samples"
        "?business_unit_id=bu_demo&limit=51",
        headers=OPERATOR,
    )
    assert too_many.status_code == 422


def test_permissions_split_read_and_write(client: TestClient) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        draft = _adopted_draft(session, created_at=now)
        session.commit()
        draft_id = str(draft.id)

    for headers in (SUPERVISOR, AUDITOR):
        summary = client.get(
            "/api/v1/knowledge/answer-evaluations/summary?business_unit_id=bu_demo",
            headers=headers,
        )
        assert summary.status_code == 200
        assert summary.json()["adopted_total"] == 1

    supervisor_write = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=SUPERVISOR,
        json={"business_unit_id": "bu_demo", "draft_id": draft_id, "verdict": "CORRECT"},
    )
    assert supervisor_write.status_code == 403
    assert supervisor_write.json()["code"] == "FORBIDDEN"

    agent_read = client.get(
        "/api/v1/knowledge/answer-evaluations/summary?business_unit_id=bu_demo",
        headers=AGENT,
    )
    assert agent_read.status_code == 403

    agent_write = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=AGENT,
        json={"business_unit_id": "bu_demo", "draft_id": draft_id, "verdict": "CORRECT"},
    )
    assert agent_write.status_code == 403

    cross_unit_read = client.get(
        "/api/v1/knowledge/answer-evaluations/summary?business_unit_id=bu_other",
        headers=OPERATOR,
    )
    assert cross_unit_read.status_code == 403
    assert cross_unit_read.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def test_existing_evaluation_is_reused_not_duplicated(client: TestClient) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as session:
        draft = _adopted_draft(session, created_at=now)
        session.add(
            AnswerQualityEvaluation(
                business_unit_id="bu_demo",
                draft_id=draft.id,
                verdict="INCORRECT",
                hallucinated=True,
                evaluator_ref="earlier-reviewer",
            )
        )
        session.commit()
        draft_id = str(draft.id)

    response = client.post(
        "/api/v1/knowledge/answer-evaluations",
        headers=OPERATOR,
        json={"business_unit_id": "bu_demo", "draft_id": draft_id, "verdict": "CORRECT"},
    )
    assert response.status_code == 200
    assert response.json()["evaluator_ref"] == "knowledge-operator-quality"

    with SessionLocal() as session:
        count = (
            session.query(AnswerQualityEvaluation)
            .filter(AnswerQualityEvaluation.draft_id == draft.id)
            .count()
        )
    assert count == 1

    summary = client.get(
        "/api/v1/knowledge/answer-evaluations/summary?business_unit_id=bu_demo",
        headers=OPERATOR,
    ).json()
    assert summary["verdict_counts"] == {"CORRECT": 1}
    assert summary["hallucination_rate"] == 0.0
