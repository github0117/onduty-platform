import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from ticket_agent.knowledge.embedding_types import EmbeddingBatch, EmbeddingProviderError
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.models import KnowledgeChunk
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.knowledge.schemas import KnowledgeDocumentCreate, KnowledgeVersionCreate
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.knowledge.vector import PostgresVector
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


def test_local_embedding_is_deterministic_and_normalized() -> None:
    provider = LocalEmbeddingProvider(dimensions=32)
    first = provider.embed_texts(["企业通知配置"])[0]
    second = provider.embed_texts(["企业通知配置"])[0]

    assert first == second
    assert len(first) == 32
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_openai_embedding_redacts_sensitive_text() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [1.0, 0.0, 0.0]},
                ]
            },
        )

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://model.example/v1",
        embedding_model_name="embedding-model",
        embedding_dimensions=3,
        embedding_fallback_to_local=False,
        model_data_redaction_enabled=True,
    )
    provider = OpenAICompatibleEmbeddingProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    embedding = provider.embed_texts(["联系 test@example.com 或 13800138000"])[0]

    assert embedding == [1.0, 0.0, 0.0]
    assert captured["input"] == ["联系 <EMAIL> 或 <MOBILE>"]


def test_openai_embedding_sends_dimensions_when_enabled() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"data": [{"embedding": [1.0, 0.0, 0.0]}]},
        )

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://model.example/v1",
        embedding_model_name="embedding-model",
        embedding_dimensions=3,
        embedding_send_dimensions=True,
        embedding_fallback_to_local=False,
    )
    provider = OpenAICompatibleEmbeddingProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.embed_texts(["企业通知配置"])

    assert captured["dimensions"] == 3


class ExplodingEmbedding:
    name = LocalEmbeddingProvider(256).name
    dimensions = 256

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        raise EmbeddingProviderError("remote embedding is down")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingProviderError("remote embedding is down")


def test_search_maps_embedding_failure_to_service_unavailable() -> None:
    with SessionLocal() as session:
        service = KnowledgeService(
            session,
            embedding_provider=LocalEmbeddingProvider(256),
        )
        document = service.create_document(
            KnowledgeDocumentCreate(
                business_unit_id="bu_embedding_unit",
                title="嵌入故障说明",
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
                content="签收后七天内可以申请退款，需要保留发票。",
                effective_from=datetime.now(UTC),
            ),
            correlation_id="embedding-unit",
        )
        service.publish_version(document.id, version.id, actor_id="admin-1")
        failing = KnowledgeService(
            session,
            embedding_provider=ExplodingEmbedding(),
        )

        with pytest.raises(ApiProblem) as error:
            failing.search(
                query="退款 发票",
                business_unit_id="bu_embedding_unit",
            )

    assert error.value.status_code == 503
    assert error.value.code == "EMBEDDING_UNAVAILABLE"


def test_postgres_ddl_uses_pgvector_column() -> None:
    ddl = str(
        CreateTable(KnowledgeChunk.__table__).compile(
            dialect=postgresql.dialect(),
        )
    )

    assert "VECTOR(256)" in ddl.upper()


def test_postgres_vector_processor_accepts_text_and_native_sequences() -> None:
    processor = PostgresVector(3).result_processor(postgresql.dialect(), None)

    assert processor("[1, 2.5, 3]") == [1.0, 2.5, 3.0]
    assert processor([1, 2.5, 3]) == [1.0, 2.5, 3.0]

