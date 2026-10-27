from uuid import UUID, uuid4

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


def _hit(
    *,
    title: str,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        title=title,
        version="1.0",
        content=f"{title} 内容",
        score=0.9,
    )


def test_evaluation_scores_chunk_and_document_level_ground_truth() -> None:
    relevant_chunk = uuid4()
    irrelevant_chunk = uuid4()
    second_chunk = uuid4()
    relevant_document = uuid4()
    cases = [
        EvaluationCase(
            query="仅声明分块",
            business_unit_id="bu",
            expected_titles=[],
            expected_chunk_ids=[str(relevant_chunk), str(second_chunk)],
        )
    ]
    hits = [
        _hit(title="无关", chunk_id=irrelevant_chunk),
        _hit(
            title="相关",
            chunk_id=relevant_chunk,
            document_id=relevant_document,
        ),
        _hit(title="相关二", chunk_id=second_chunk),
    ]

    report = score_evaluation(cases, [hits], top_k=5)
    case = report["cases"][0]  # type: ignore[index]

    assert case["no_grounding_correct"] is None
    assert case["chunk_recall_at_k"] == 1.0
    assert case["chunk_reciprocal_rank"] == 0.5
    assert case["context_precision"] == 2 / 3
    assert case["passed"] is True
    assert report["chunk_recall_at_k"] == 1.0
    assert report["chunk_mrr"] == 0.5
    assert report["context_precision"] == 2 / 3
    assert report["passed_cases"] == 1


def test_evaluation_counts_negative_document_violation_as_failure() -> None:
    expected_document = uuid4()
    forbidden_document = uuid4()
    cases = [
        EvaluationCase(
            query="禁止召回",
            business_unit_id="bu",
            expected_titles=[],
            expected_document_ids=[str(expected_document)],
            negative_document_ids=[str(forbidden_document)],
        )
    ]
    hits = [
        _hit(title="允许文档", document_id=expected_document),
        _hit(title="禁止文档", document_id=forbidden_document),
    ]

    report = score_evaluation(cases, [hits], top_k=5)
    case = report["cases"][0]  # type: ignore[index]

    assert case["document_recall_at_k"] == 1.0
    assert case["negative_document_hit"] is True
    assert case["passed"] is False
    assert report["negative_violation_rate"] == 1.0
    assert report["passed_cases"] == 0


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



def test_rrf_fusion_keeps_strongest_vector_score() -> None:
    from ticket_agent.knowledge.service import _rrf_fuse

    shared = _candidate(content="退款政策", vector_score=0.20, title="退款政策")
    other = _candidate(content="VPN", vector_score=0.40, title="VPN")
    rewritten = _candidate(content="退款政策", vector_score=0.75, title="退款政策")
    rewritten = RetrievalCandidate(
        chunk_id=shared.chunk_id,
        document_id=shared.document_id,
        title=rewritten.title,
        version=rewritten.version,
        content=rewritten.content,
        vector_score=rewritten.vector_score,
    )

    fused = _rrf_fuse([[other, shared], [rewritten]], limit=5, k=60)

    by_id = {candidate.chunk_id: candidate for candidate in fused}
    assert by_id[shared.chunk_id].vector_score == 0.75
    assert fused[0].chunk_id == shared.chunk_id
