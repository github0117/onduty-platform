import httpx
import pytest

from ticket_agent.knowledge.query_rewrite import (
    OpenAICompatibleQueryRewriter,
    QueryRewriteError,
    build_query_rewriter,
    build_search_queries,
    extract_keywords,
    resolve_query,
    sanitize_variants,
)
from ticket_agent.shared.settings import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "query_rewrite_base_url": "http://rewriter.local/v1",
        "query_rewrite_api_key": "",
        "query_rewrite_model_name": "rewrite-model",
        "knowledge_query_rewrite_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return Settings(**values)


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, timeout=1.0)


def test_query_without_history_is_not_rewritten() -> None:
    assert build_search_queries(
        "退款怎么申请",
        None,
        max_history_turns=3,
        enabled=True,
    ) == ["退款怎么申请"]


def test_anaphora_resolves_to_recent_model_number() -> None:
    resolution = resolve_query(
        "这个怎么退货",
        ["我刚才买了 HX-9080B 保温杯，有点漏水"],
    )

    assert resolution.context_used is True
    assert resolution.standalone == "HX-9080B怎么退货"


def test_anaphora_without_code_prepends_previous_turn() -> None:
    resolution = resolve_query(
        "那退款呢",
        ["我买的保温杯漏水了", "客服说要拍照"],
    )

    assert resolution.context_used is True
    assert resolution.standalone == "客服说要拍照\n那退款呢"


def test_question_without_anaphora_keeps_original_even_with_history() -> None:
    assert build_search_queries(
        "退款怎么申请",
        ["我买的保温杯漏水了"],
        max_history_turns=3,
        enabled=True,
    ) == ["退款怎么申请"]


def test_history_window_is_limited() -> None:
    resolution = resolve_query(
        "它怎么处理",
        ["第一轮", "第二轮 HX-100", "第三轮", "第四轮"],
        max_history_turns=2,
    )

    # Only the last two turns are considered; the model number in the second
    # turn is outside the window.
    assert resolution.standalone == "第四轮\n它怎么处理"


def test_disabled_context_resolution_keeps_original() -> None:
    assert build_search_queries(
        "那退款呢",
        ["我买的保温杯漏水了"],
        max_history_turns=3,
        enabled=False,
    ) == ["那退款呢"]


def test_keywords_are_deduplicated_and_keep_model_codes() -> None:
    keywords = extract_keywords("HX-9080B 退款 退款 流程")

    assert "hx-9080b" in keywords
    assert keywords.count("退款") == 1


def test_build_query_rewriter_requires_enabled_and_endpoint() -> None:
    assert build_query_rewriter(Settings(knowledge_query_rewrite_enabled=False)) is None
    assert (
        build_query_rewriter(
            Settings(
                knowledge_query_rewrite_enabled=True,
                query_rewrite_base_url="",
                query_rewrite_model_name="",
            )
        )
        is None
    )


def test_rewriter_parses_json_array_and_caps_variants() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Content-Type"] == "application/json"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '["退款到账要多久", "退款申请流程",'
                                ' "退款申请流程", ""]'
                            )
                        }
                    }
                ]
            },
        )

    rewriter = OpenAICompatibleQueryRewriter(
        _settings(),
        client=_client(httpx.MockTransport(handler)),
    )

    assert rewriter.rewrite(query="那退款呢", variants=2) == [
        "退款到账要多久",
        "退款申请流程",
    ]


def test_rewriter_accepts_fenced_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '```json\n["退款到账时间"]\n```'
                        }
                    }
                ]
            },
        )

    rewriter = OpenAICompatibleQueryRewriter(
        _settings(),
        client=_client(httpx.MockTransport(handler)),
    )

    assert rewriter.rewrite(query="那退款呢", variants=1) == ["退款到账时间"]


def test_rewriter_rejects_empty_result() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '["那退款呢"]'}}]},
        )

    rewriter = OpenAICompatibleQueryRewriter(
        _settings(),
        client=_client(httpx.MockTransport(handler)),
    )

    with pytest.raises(QueryRewriteError):
        rewriter.rewrite(query="那退款呢", variants=2)


def test_rewriter_wraps_http_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    rewriter = OpenAICompatibleQueryRewriter(
        _settings(),
        client=_client(httpx.MockTransport(handler)),
    )

    with pytest.raises(QueryRewriteError):
        rewriter.rewrite(query="那退款呢", variants=2)


def test_sanitize_keeps_leading_digits() -> None:
    assert sanitize_variants(
        ["- 20261027 订单退款", "20261027 订单退款"],
        original="退款",
        limit=5,
    ) == ["20261027 订单退款"]


def test_sanitize_accepts_query_objects_from_real_model() -> None:
    assert sanitize_variants(
        [
            {"query": "困难高校毕业生离校前能领哪些补贴？"},
            {"text": "高校困难毕业生离校前有什么补助？"},
            {"rewrite": "困难毕业生离校前补贴政策是什么？"},
            {"other": "ignored"},
        ],
        original="困难高校毕业生在离校前可以享受什么补贴呢？",
        limit=5,
    ) == [
        "困难高校毕业生离校前能领哪些补贴？",
        "高校困难毕业生离校前有什么补助？",
        "困难毕业生离校前补贴政策是什么？",
    ]
