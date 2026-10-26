import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import Float, bindparam, cast, create_engine, select
from sqlalchemy.orm import Session

from ticket_agent.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_pgvector_distance_returns_float_not_vector() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with Session(engine) as session:
            document = KnowledgeDocument(
                business_unit_id="bu_pgvector_test",
                title="pgvector regression",
                doc_type="SOP",
                owner_id="test",
                scope_json={},
                status="DRAFT",
            )
            session.add(document)
            session.flush()
            version = KnowledgeVersion(
                document_id=document.id,
                version_label=uuid4().hex,
                status="DRAFT",
                content_text="pgvector distance regression",
                content_hash=uuid4().hex,
                effective_from=datetime.now(UTC),
                embedding_model="test-vector",
            )
            session.add(version)
            session.flush()
            embedding = [1.0] + [0.0] * 255
            chunk = KnowledgeChunk(
                knowledge_version_id=version.id,
                ordinal=0,
                content="pgvector distance regression",
                metadata_json={},
                embedding=embedding,
            )
            session.add(chunk)
            session.flush()

            distance = cast(
                KnowledgeChunk.embedding.op("<=>")(
                    bindparam(
                        "query_embedding",
                        embedding,
                        type_=KnowledgeChunk.embedding.type,
                    )
                ),
                Float,
            )
            result = session.scalar(
                select(distance).where(KnowledgeChunk.id == chunk.id)
            )

            assert isinstance(result, float)
            assert result == pytest.approx(0.0)
            session.rollback()
    finally:
        engine.dispose()
