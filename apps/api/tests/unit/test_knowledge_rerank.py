import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.rerank import (
    DashScopeReranker,
    ExternalHTTPReranker,
    rerank_fallback_total,
    reset_rerank_metrics,
)
from ticket_agent.knowledge.retrieval import (
    HybridReranker,
    RetrievalCandidate,
)
from ticket_agent.knowledge.schemas import (
    KnowledgeDocumentCreate,
    KnowledgeVersionCreate,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


def _candidate(index: int, *, vector_score: float = 0.5) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=UUID(int=index + 1),
        document_id=UUID(int=100 + index),
        title=f"退款政策 {index}",
        version="1.0",
        content=f"签收后七天内可以申请退款，第 {index} 条说明。",
        vector_score=vector_score,
    )


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "test",
        "knowledge_rerank_provider": "external",
        "rerank_base_url": "http://rerank.example/v1",
        "rerank_model_name": "bge-reranker-v2-m3",
        "knowledge_rerank_min_candidates": 1,
        "knowledge_rerank_trigger_score": 0.0,
        "knowledge_rerank_max_candidates": 30,
        "rerank_fallback_to_local": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client(handler, requests: list[dict] | None = None) -> httpx.Client:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(json.loads(request.content))
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped))


def _ok_handler(order: list[int]):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": index, "relevance_score": 0.9 - position * 0.1}
                    for position, index in enumerate(order)
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 0},
            },
        )

    return handler


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    reset_rerank_metrics()


def test_remote_scores_replace_local_ranking() -> None:
    candidates = [_candidate(0), _candidate(1), _candidate(2)]
    requests: list[dict] = []
    reranker = ExternalHTTPReranker(
        _settings(),
        client=_client(_ok_handler([2, 0, 1]), requests),
    )

    ranked = reranker.rerank(query="退款", candidates=candidates, top_k=2)

    assert [item.candidate.chunk_id for item in ranked] == [
        candidates[2].chunk_id,
        candidates[0].chunk_id,
    ]
    assert ranked[0].final_score == pytest.approx(0.9)
    assert len(requests) == 1
    assert requests[0]["model"] == "bge-reranker-v2-m3"
    assert len(requests[0]["documents"]) == 3
    assert requests[0]["top_n"] == 2


def test_candidates_are_capped_before_the_remote_call() -> None:
    candidates = [_candidate(index) for index in range(40)]
    requests: list[dict] = []
    reranker = ExternalHTTPReranker(
        _settings(knowledge_rerank_max_candidates=30),
        client=_client(_ok_handler(list(range(30))), requests),
    )

    reranker.rerank(query="退款", candidates=candidates, top_k=100)

    assert len(requests[0]["documents"]) == 30
    assert requests[0]["top_n"] == 30


def test_remote_server_error_falls_back_and_counts() -> None:
    candidates = [_candidate(0), _candidate(1)]
    reranker = ExternalHTTPReranker(
        _settings(),
        client=_client(lambda _request: httpx.Response(500)),
    )

    ranked = reranker.rerank(query="退款", candidates=candidates, top_k=2)

    expected = HybridReranker(vector_weight=0.6, lexical_weight=0.4).rerank(
        query="退款",
        candidates=candidates,
        top_k=2,
    )
    assert [item.candidate.chunk_id for item in ranked] == [
        item.candidate.chunk_id for item in expected
    ]
    assert rerank_fallback_total() == 1


def test_remote_timeout_falls_back_and_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("rerank timed out", request=request)

    candidates = [_candidate(0)]
    reranker = ExternalHTTPReranker(_settings(), client=_client(handler))

    ranked = reranker.rerank(query="退款", candidates=candidates, top_k=1)

    assert [item.candidate.chunk_id for item in ranked] == [candidates[0].chunk_id]
    assert rerank_fallback_total() == 1


def test_fallback_disabled_propagates_failure() -> None:
    reranker = ExternalHTTPReranker(
        _settings(rerank_fallback_to_local=False),
        client=_client(lambda _request: httpx.Response(502)),
    )

    with pytest.raises(RuntimeError):
        reranker.rerank(query="退款", candidates=[_candidate(0)], top_k=1)
    assert rerank_fallback_total() == 0


def test_invalid_reranker_index_falls_back() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"index": 9, "relevance_score": 0.8}]})

    reranker = ExternalHTTPReranker(_settings(), client=_client(handler))

    ranked = reranker.rerank(query="退款", candidates=[_candidate(0)], top_k=1)

    assert [item.candidate.chunk_id for item in ranked] == [_candidate(0).chunk_id]
    assert rerank_fallback_total() == 1


def test_small_confident_pool_skips_the_remote_call() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("remote reranker must not be called")

    candidates = [_candidate(0, vector_score=0.9), _candidate(1, vector_score=0.8)]
    reranker = ExternalHTTPReranker(
        _settings(knowledge_rerank_min_candidates=10, knowledge_rerank_trigger_score=0.5),
        client=_client(handler),
    )

    ranked = reranker.rerank(query="退款", candidates=candidates, top_k=2)

    assert len(ranked) == 2
    assert rerank_fallback_total() == 0


def test_low_confidence_pool_triggers_the_remote_call() -> None:
    candidates = [_candidate(0, vector_score=0.2), _candidate(1, vector_score=0.1)]
    requests: list[dict] = []
    reranker = ExternalHTTPReranker(
        _settings(knowledge_rerank_min_candidates=10, knowledge_rerank_trigger_score=0.5),
        client=_client(_ok_handler([1, 0]), requests),
    )

    ranked = reranker.rerank(query="退款", candidates=candidates, top_k=2)

    assert len(requests) == 1
    assert ranked[0].final_score == pytest.approx(0.9)


def test_dashscope_reranker_uses_service_payload() -> None:
    requests: list[dict] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.95},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
                "usage": {"total_tokens": 21},
            },
        )

    reranker = DashScopeReranker(
        _settings(
            knowledge_rerank_provider="dashscope",
            rerank_base_url="",
            rerank_model_name="gte-rerank-v2",
            model_api_key="runtime-key",
        ),
        client=_client(handler, requests),
    )
    ranked = reranker.rerank(
        query="退款",
        candidates=[_candidate(0), _candidate(1)],
        top_k=2,
    )

    assert reranker.name == "dashscope:gte-rerank-v2"
    assert ranked[0].candidate.chunk_id == UUID(int=2)
    assert requests[0]["input"]["query"] == "退款"  # type: ignore[index]
    assert requests[0]["parameters"]["top_n"] == 2  # type: ignore[index]


def test_dashscope_reranker_falls_back_on_server_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "InternalError"})

    reranker = DashScopeReranker(
        _settings(
            knowledge_rerank_provider="dashscope",
            rerank_base_url="",
            rerank_model_name="gte-rerank-v2",
            model_api_key="runtime-key",
        ),
        client=_client(handler),
    )
    ranked = reranker.rerank(
        query="退款",
        candidates=[_candidate(0), _candidate(1)],
        top_k=2,
    )

    assert len(ranked) == 2
    assert rerank_fallback_total() == 1


def test_empty_candidates_skip_the_remote_call() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("remote reranker must not be called")

    reranker = ExternalHTTPReranker(_settings(), client=_client(handler))

    assert reranker.rerank(query="退款", candidates=[], top_k=3) == []


class ExplodingReranker:
    name = "exploding"

    def rerank(self, *, query, candidates, top_k):  # noqa: ANN001, ANN201
        raise RuntimeError("reranker is down")


def test_search_maps_reranker_failure_to_service_unavailable() -> None:
    with SessionLocal() as session:
        service = KnowledgeService(
            session,
            embedding_provider=LocalEmbeddingProvider(256),
        )
        document = service.create_document(
            KnowledgeDocumentCreate(
                business_unit_id="bu_rerank_unit",
                title="重排失败说明",
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
            correlation_id="rerank-unit",
        )
        service.publish_version(document.id, version.id, actor_id="admin-1")
        failing = KnowledgeService(
            session,
            embedding_provider=LocalEmbeddingProvider(256),
            reranker=ExplodingReranker(),  # type: ignore[arg-type]
        )

        with pytest.raises(ApiProblem) as error:
            failing.search(
                query="退款 发票",
                business_unit_id="bu_rerank_unit",
            )

    assert error.value.status_code == 503
    assert error.value.code == "RERANK_UNAVAILABLE"
