from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from ticket_agent.knowledge.embedding_types import (
    EmbeddingBatch,
    EmbeddingProviderError,
)
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeVersion,
)
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.knowledge.reindex import KnowledgeReindexService
from ticket_agent.knowledge.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeVersionCreate,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings

BUSINESS_UNIT_ID = "bu_reindex"


class NamedLocalProvider(LocalEmbeddingProvider):
    def __init__(self, name: str, dimensions: int = 256) -> None:
        super().__init__(dimensions)
        self._name = name

    @property
    def name(self) -> str:
        return self._name


class FailingProvider:
    name = "remote-broken"
    dimensions = 256

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        raise EmbeddingProviderError("remote embedding is down")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("remote embedding is down")


def _create_version(session: object, content: str) -> tuple[KnowledgeDocument, KnowledgeVersion]:
    service = KnowledgeService(
        session,  # type: ignore[arg-type]
        embedding_provider=LocalEmbeddingProvider(256),
    )
    document = service.create_document(
        KnowledgeDocumentCreate(
            business_unit_id=BUSINESS_UNIT_ID,
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
            version_label=f"1.0-{uuid4().hex[:8]}",
            content=content,
            effective_from=datetime.now(UTC),
        ),
        correlation_id="reindex-test",
    )
    return document, version


def test_duplicate_job_creation_reuses_active_job() -> None:
    with SessionLocal() as session:
        service = KnowledgeReindexService(
            session,
            embedding_provider=NamedLocalProvider("bge-m3"),
        )
        first = service.create_job(
            business_unit_id=BUSINESS_UNIT_ID,
            requested_by="admin-1",
            correlation_id="reindex-1",
        )
        second = service.create_job(
            business_unit_id=BUSINESS_UNIT_ID,
            requested_by="admin-1",
            correlation_id="reindex-2",
        )

    assert first.created is True
    assert second.created is False
    assert second.job.id == first.job.id


def test_run_job_rebuilds_versions_for_new_embedding_model() -> None:
    with SessionLocal() as session:
        _document, version = _create_version(session, "签收后七天内可以申请退款。")
        version.embedding_model = "legacy-model-256"
        session.commit()

        service = KnowledgeReindexService(
            session,
            embedding_provider=NamedLocalProvider("bge-m3"),
        )
        submission = service.create_job(
            business_unit_id=BUSINESS_UNIT_ID,
            requested_by="admin-1",
            correlation_id="reindex-1",
        )
        job = service.run_job(submission.job.id, correlation_id="reindex-1")
        session.refresh(version)
        chunks = session.query(KnowledgeChunk).filter_by(
            knowledge_version_id=version.id
        ).all()

    assert job.status == "SUCCEEDED"
    assert job.processed_versions == 1
    assert job.failed_versions == 0
    assert job.attempt_count == 1
    assert version.embedding_model == "bge-m3"
    assert version.embedding_indexed_at is not None
    assert chunks
    assert all(chunk.metadata_json["embedding_model"] == "bge-m3" for chunk in chunks)
    assert all(chunk.metadata_json["chunking_version"] == "v1" for chunk in chunks)


def test_second_run_skips_already_current_versions() -> None:
    with SessionLocal() as session:
        _create_version(session, "发票在确认收货后开具。")
        provider = NamedLocalProvider("bge-m3")
        service = KnowledgeReindexService(session, embedding_provider=provider)
        service.run_job(
            service.create_job(
                business_unit_id=BUSINESS_UNIT_ID,
                requested_by="admin-1",
                correlation_id="reindex-1",
            ).job.id
        )
        second = service.create_job(
            business_unit_id=BUSINESS_UNIT_ID,
            requested_by="admin-1",
            correlation_id="reindex-2",
        )
        job = service.run_job(second.job.id)

    assert second.created is True
    assert job.status == "SUCCEEDED"
    assert job.processed_versions == 0
    assert job.skipped_versions == 1


def test_reindex_with_v2_chunking_writes_section_metadata() -> None:
    with SessionLocal() as session:
        _document, version = _create_version(session, "退款政策\n\n签收后七天内可以申请退款。")
        version.content_blocks_json = {
            "version": 1,
            "blocks": [
                {"kind": "heading", "text": "退款政策", "level": 1},
                {"kind": "paragraph", "text": "签收后七天内可以申请退款。"},
            ],
            "warnings": [],
        }
        session.commit()

        service = KnowledgeReindexService(
            session,
            embedding_provider=NamedLocalProvider("bge-m3"),
        )
        job = service.run_job(
            service.create_job(
                business_unit_id=BUSINESS_UNIT_ID,
                requested_by="admin-1",
                correlation_id="reindex-v2",
                chunking_version="v2",
            ).job.id
        )
        chunks = session.query(KnowledgeChunk).filter_by(
            knowledge_version_id=version.id
        ).all()

    assert job.status == "SUCCEEDED"
    assert job.target_chunking_version == "v2"
    assert chunks[0].metadata_json["chunking_version"] == "v2"
    assert chunks[0].metadata_json["section_path"] == ["退款政策"]


def test_failed_versions_retry_then_dead_letter() -> None:
    with SessionLocal() as session:
        _document, version = _create_version(session, "跨境订单不支持无理由退款。")
        original_model = version.embedding_model
        service = KnowledgeReindexService(session, embedding_provider=FailingProvider())
        job_id = service.create_job(
            business_unit_id=BUSINESS_UNIT_ID,
            requested_by="admin-1",
            correlation_id="reindex-fail",
        ).job.id

        first = service.run_job(job_id)
        first_status = first.status
        first_failed = first.failed_versions
        first_error = first.last_error or ""
        second_status = service.run_job(job_id).status
        third_status = service.run_job(job_id).status
        session.refresh(version)
        model_after = version.embedding_model

    assert first_status == "FAILED"
    assert first_failed == 1
    assert "Embedding generation failed" in first_error
    assert second_status == "FAILED"
    assert third_status == "DEAD_LETTER"
    assert model_after == original_model


def test_embedding_failure_aborts_version_creation() -> None:
    with SessionLocal() as session:
        service = KnowledgeService(session, embedding_provider=FailingProvider())
        document = service.create_document(
            KnowledgeDocumentCreate(
                business_unit_id=BUSINESS_UNIT_ID,
                title="跨境售后",
                doc_type="SOP",
                owner_id="admin-1",
                scope={},
            ),
            actor_id="admin-1",
        )
        with pytest.raises(ApiProblem) as exc_info:
            service.create_version(
                document.id,
                KnowledgeVersionCreate(
                    version_label="1.0",
                    content="跨境订单不支持无理由退款。",
                    effective_from=datetime.now(UTC),
                ),
            )
        session.rollback()
        versions = (
            session.query(KnowledgeVersion)
            .filter_by(document_id=document.id)
            .count()
        )

    assert exc_info.value.code == "EMBEDDING_UNAVAILABLE"
    assert exc_info.value.status_code == 503
    assert versions == 0


def test_embedding_fallback_records_local_model_and_flag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("embedding endpoint down", request=request)

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model_name="bge-m3",
        embedding_dimensions=8,
        embedding_fallback_to_local=True,
    )
    provider = OpenAICompatibleEmbeddingProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with SessionLocal() as session:
        service = KnowledgeService(session, embedding_provider=provider)
        document = service.create_document(
            KnowledgeDocumentCreate(
                business_unit_id=BUSINESS_UNIT_ID,
                title="通知配置",
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
                content="管理员可以在后台打开消息通知。",
                effective_from=datetime.now(UTC),
            ),
        )
        chunks = session.query(KnowledgeChunk).filter_by(
            knowledge_version_id=version.id
        ).all()

    assert version.embedding_model == "local-hash-8"
    assert chunks
    assert all(chunk.metadata_json["embedding_fallback_used"] is True for chunk in chunks)
    assert all(chunk.metadata_json["embedding_model"] == "local-hash-8" for chunk in chunks)
