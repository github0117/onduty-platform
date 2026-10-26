import json

import httpx
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.models import KnowledgeChunk
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.knowledge.vector import PostgresVector
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

