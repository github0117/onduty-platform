from uuid import uuid4

from ticket_agent.knowledge.retrieval import RetrievalCandidate
from ticket_agent.knowledge.service import KnowledgeService, _rrf_fuse
from ticket_agent.knowledge.tokenizer import (
    MAX_QUERY_TOKENS,
    build_lexical_text,
    build_tsquery,
    tokenize,
)
from ticket_agent.shared.db import SessionLocal


def _candidate(chunk_id: object) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,  # type: ignore[arg-type]
        document_id=uuid4(),
        title="退款政策",
        version="1.0",
        content="签收后七天内可以申请退款。",
        vector_score=0.5,
    )


def test_tokenize_keeps_cjk_unigrams_bigrams_and_latin_codes() -> None:
    tokens = tokenize("退款 Policy V2.1 已生效")

    assert "退" in tokens
    assert "款" in tokens
    assert "退款" in tokens
    assert "policy" in tokens
    assert "v2.1" in tokens


def test_tokenize_drops_chinese_stopwords() -> None:
    tokens = tokenize("我的订单")

    assert "的" not in tokens
    assert "我" not in tokens
    assert "订单" in tokens


def test_build_lexical_text_is_stable_space_joined_tokens() -> None:
    text = "退款政策"

    assert build_lexical_text(text) == " ".join(tokenize(text))
    assert build_lexical_text(text) == build_lexical_text(text)


def test_build_tsquery_dedupes_and_caps_tokens() -> None:
    query = "退款 退款 " + " ".join(f"token{index}" for index in range(80))
    tsquery = build_tsquery(query)
    parts = tsquery.split(" | ")

    assert len(parts) == MAX_QUERY_TOKENS
    assert len(set(parts)) == len(parts)
    assert parts[:2] == ["退", "款"]


def test_build_tsquery_splits_hyphenated_codes_into_or_terms() -> None:
    # PostgreSQL parses 'hx-9080b' as an adjacency phrase; the query must stay
    # a plain OR so separated spellings still match.
    assert build_tsquery("HX-9080B") == "hx | 9080b"
    assert build_tsquery("退款 HX-9080B") == "退 | 款 | 退款 | hx | 9080b"


def test_build_tsquery_returns_empty_for_blank_or_stopword_only_query() -> None:
    assert build_tsquery("   ") == ""
    assert build_tsquery("的了和与") == ""


def test_rrf_fuse_rewards_documents_found_by_both_channels() -> None:
    shared = _candidate(uuid4())
    dense_only = _candidate(uuid4())
    lexical_only = _candidate(uuid4())

    fused = _rrf_fuse(
        [
            [shared, dense_only],
            [shared, lexical_only],
        ],
        limit=3,
        k=60,
    )

    assert fused[0].chunk_id == shared.chunk_id
    assert len(fused) == 3
    assert {item.chunk_id for item in fused} == {
        shared.chunk_id,
        dense_only.chunk_id,
        lexical_only.chunk_id,
    }


def test_rrf_fuse_dedupes_and_truncates() -> None:
    first = _candidate(uuid4())
    second = _candidate(uuid4())

    fused = _rrf_fuse([[first, second], [first, second]], limit=1, k=60)

    assert [item.chunk_id for item in fused] == [first.chunk_id]


def test_sqlite_session_degrades_hybrid_setting_to_dense(monkeypatch) -> None:
    with SessionLocal() as session:
        service = KnowledgeService(session)
        monkeypatch.setattr(service.settings, "knowledge_retrieval_mode", "hybrid")

        assert service.retrieval_mode == "dense"
