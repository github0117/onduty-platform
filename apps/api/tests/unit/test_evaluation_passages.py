from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from ticket_agent.knowledge.evaluation_service import KnowledgeEvaluationService
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.metrics import embedding_quality
from ticket_agent.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeVersion,
)
from ticket_agent.knowledge.reindex import KnowledgeReindexService
from ticket_agent.knowledge.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeEvaluationCaseCreate,
    KnowledgeEvaluationPassage,
    KnowledgeEvaluationRunCreate,
    KnowledgeVersionCreate,
)
from ticket_agent.knowledge.service import (
    KnowledgeHit,
    KnowledgeService,
    _prune_context_hits,
)
from ticket_agent.shared.db import SessionLocal

CONTENT = (
    "退款政策说明：签收后七天内可以申请退款，退款原路退回。"
    "跨境订单不支持无理由退款，需要联系人工客服处理。"
)


def _published_document(
    session: object,
    *,
    business_unit_id: str,
    content: str = CONTENT,
) -> tuple[KnowledgeDocument, KnowledgeVersion]:
    service = KnowledgeService(
        session,  # type: ignore[arg-type]
        embedding_provider=LocalEmbeddingProvider(256),
    )
    document = service.create_document(
        KnowledgeDocumentCreate(
            business_unit_id=business_unit_id,
            title="退款政策",
            doc_type="SOP",
            owner_id="admin-1",
            scope={},
        ),
        actor_id="admin-1",
    )
    version = service.create_version(
        document.id,
        KnowledgeVersionCreate(
            version_label="1.0",
            content=content,
            effective_from=datetime.now(UTC),
        ),
        correlation_id="passage-test",
    )
    service.publish_version(document.id, version.id, actor_id="admin-1")
    return document, version


def _create_passage_case(
    session: object,
    *,
    business_unit_id: str,
    document_id: object,
    text: str,
) -> object:
    return KnowledgeEvaluationService(  # type: ignore[arg-type]
        session
    ).create_case(
        KnowledgeEvaluationCaseCreate(
            business_unit_id=business_unit_id,
            name="退款时限",
            query="签收后几天可以退款",
            expected_passages=[
                KnowledgeEvaluationPassage(
                    document_id=document_id,  # type: ignore[arg-type]
                    text=text,
                )
            ],
        ),
        actor_id="admin-1",
    )


def _run(session: object, business_unit_id: str) -> object:
    return KnowledgeEvaluationService(  # type: ignore[arg-type]
        session
    ).run(
        KnowledgeEvaluationRunCreate(business_unit_id=business_unit_id),
        actor_id="admin-1",
    )


def test_passage_case_resolves_to_chunk_and_passes() -> None:
    with SessionLocal() as session:
        document, _version = _published_document(
            session, business_unit_id="bu_passage_unit"
        )
        _create_passage_case(
            session,
            business_unit_id="bu_passage_unit",
            document_id=document.id,
            text="签收后七天内可以申请退款",
        )

        run = _run(session, "bu_passage_unit")

    assert run.status == "SUCCEEDED"
    assert run.verdict == "PASS"
    assert run.chunk_recall_at_k == 1.0
    assert run.results_json[0]["passed"] is True
    assert "unresolved_passages" not in run.results_json[0]


def test_passage_case_survives_reindex_with_new_chunk_ids() -> None:
    with SessionLocal() as session:
        document, version = _published_document(
            session, business_unit_id="bu_passage_reindex"
        )
        case = _create_passage_case(
            session,
            business_unit_id="bu_passage_reindex",
            document_id=document.id,
            text="签收后七天内可以申请退款",
        )
        # A legacy cached chunk id must not affect a passage-based case.
        case.expected_chunk_ids_json = ["00000000-0000-0000-0000-000000000001"]
        session.commit()

        first_run = _run(session, "bu_passage_reindex")
        old_chunk_ids = list(first_run.results_json[0]["returned_chunk_ids"])
        assert old_chunk_ids

        rebuilt = KnowledgeService(
            session, embedding_provider=LocalEmbeddingProvider(256)
        ).rebuild_version_chunks(version.id, correlation_id="passage-reindex")
        assert rebuilt is True
        session.refresh(case)
        assert case.expected_chunk_ids_json == [
            "00000000-0000-0000-0000-000000000001"
        ]
        new_chunk_ids = list(
            session.scalars(
                select(KnowledgeChunk.id).where(
                    KnowledgeChunk.knowledge_version_id == version.id
                )
            )
        )
        assert {str(item) for item in new_chunk_ids}.isdisjoint(old_chunk_ids)

        stale = KnowledgeReindexService(session).stale_evaluation_chunk_refs(
            "bu_passage_reindex"
        )
        second_run = _run(session, "bu_passage_reindex")

    assert stale == 0
    assert second_run.verdict == "PASS"
    assert second_run.chunk_recall_at_k == 1.0


def test_unresolved_passage_fails_the_run_loudly() -> None:
    with SessionLocal() as session:
        document, _version = _published_document(
            session, business_unit_id="bu_passage_missing"
        )
        _create_passage_case(
            session,
            business_unit_id="bu_passage_missing",
            document_id=document.id,
            text="完全不存在的段落内容，只有这段文字",
        )

        run = _run(session, "bu_passage_missing")

    assert run.status == "SUCCEEDED"
    assert run.verdict == "FAIL"
    assert run.passed_cases == 0
    assert "passage" in (run.error_message or "")
    missing = run.results_json[0]["unresolved_passages"]
    assert missing and missing[0]["reason"] == "text_not_found"


def test_prune_context_hits_drops_same_document_duplicates() -> None:
    import uuid

    document_id = uuid.uuid4()
    other_document_id = uuid.uuid4()
    content = "签收后七天内可以申请退款，退款原路退回。" * 3
    hits = [
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=document_id,
            title="退款政策",
            version="1.0",
            content=content,
            score=0.9,
        ),
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=document_id,
            title="退款政策",
            version="1.0",
            content=f" {content} ",
            score=0.8,
        ),
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=other_document_id,
            title="另一份退款政策",
            version="1.0",
            content=content,
            score=0.7,
        ),
    ]

    pruned = _prune_context_hits(hits, max_chars=0)

    assert [hit.document_id for hit in pruned] == [document_id, other_document_id]


def test_prune_context_hits_caps_total_characters() -> None:
    import uuid

    hits = [
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            title="文档一",
            version="1.0",
            content="甲" * 100,
            score=0.9,
        ),
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            title="文档二",
            version="1.0",
            content="乙" * 100,
            score=0.8,
        ),
        KnowledgeHit(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            title="文档三",
            version="1.0",
            content="丙" * 10,
            score=0.7,
        ),
    ]

    pruned = _prune_context_hits(hits, max_chars=150)

    assert [hit.title for hit in pruned] == ["文档一", "文档三"]


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("local-hash-256", "demo"),
        ("openai-compatible:text-embedding-v3", "semantic"),
        ("BAAI/bge-m3", "semantic"),
    ],
)
def test_embedding_quality_labels_demo_mode(model_name: str, expected: str) -> None:
    assert embedding_quality(model_name) == expected
