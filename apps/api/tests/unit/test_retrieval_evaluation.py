from uuid import uuid4

import httpx

from ticket_agent.knowledge.evaluation import EvaluationCase, score_evaluation
from ticket_agent.knowledge.rerank import ExternalHTTPReranker
from ticket_agent.knowledge.retrieval import HybridReranker, RetrievalCandidate
from ticket_agent.knowledge.scope import scope_matches
from ticket_agent.knowledge.service import KnowledgeHit
from ticket_agent.shared.settings import Settings


def _candidate(
    *,
    content: str,
    vector_score: float,
    title: str,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        title=title,
        version="1.0",
        content=content,
        vector_score=vector_score,
    )


def test_hybrid_reranker_boosts_exact_lexical_match() -> None:
    reranker = HybridReranker(vector_weight=0.6, lexical_weight=0.4)
    candidates = [
        _candidate(
            content="账号安全事件处理说明",
            vector_score=0.95,
            title="安全响应",
        ),
        _candidate(
            content="管理员进入设置中心配置团队消息通知。",
            vector_score=0.60,
            title="企业通知配置指南",
        ),
    ]

    ranked = reranker.rerank(
        query="如何配置团队消息通知",
        candidates=candidates,
        top_k=2,
    )

    assert ranked[0].candidate.title == "企业通知配置指南"
    assert ranked[0].lexical_score > 0


def test_evaluation_reports_recall_mrr_and_no_grounding() -> None:
    cases = [
        EvaluationCase(
            query="通知配置",
            business_unit_id="bu",
            expected_titles=["通知指南"],
        ),
        EvaluationCase(
            query="不存在的问题",
            business_unit_id="bu",
            expected_titles=[],
            expect_no_grounding=True,
        ),
    ]
    hit = KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        title="通知指南",
        version="1.0",
        content="通知配置内容",
        score=0.9,
    )

    report = score_evaluation(cases, [[hit], []], top_k=5)

    assert report["recall_at_k"] == 1.0
    assert report["mrr"] == 1.0
    assert report["no_grounding_accuracy"] == 1.0


def test_scope_matches_org_descendants_and_wildcards() -> None:
    assert scope_matches(
        {"organizations": ["acme"]},
        {"organizations": "acme/sales"},
    )
    assert scope_matches(
        {"products": ["admin-*"]},
        {"products": "admin-portal"},
    )
    assert not scope_matches(
        {"organizations": ["acme"]},
        {"organizations": "other/sales"},
    )
    assert not scope_matches(
        {"organizations": ["acme"]},
        {},
    )


def test_external_reranker_uses_provider_scores() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.95},
                    {"index": 0, "relevance_score": 0.20},
                ]
            },
        )

    settings = Settings(
        rerank_base_url="https://rerank.example/v1",
        rerank_api_key="rerank-secret",
        rerank_model_name="cross-encoder",
        rerank_fallback_to_local=False,
    )
    reranker = ExternalHTTPReranker(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    candidates = [
        _candidate(content="first", vector_score=0.9, title="First"),
        _candidate(content="second", vector_score=0.5, title="Second"),
    ]

    ranked = reranker.rerank(query="second", candidates=candidates, top_k=2)

    assert [item.candidate.title for item in ranked] == ["Second", "First"]
    assert requests[0].url.path == "/v1/rerank"
    assert requests[0].headers["Authorization"] == "Bearer rerank-secret"

