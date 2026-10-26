import json
from typing import Any

import httpx
import pytest

from ticket_agent.classification.classifier import MockClassifier
from ticket_agent.knowledge.claim_verifier import ClaimToVerify
from ticket_agent.model_gateway.local import LocalModelGateway
from ticket_agent.model_gateway.openai_compatible import OpenAICompatibleGateway
from ticket_agent.model_gateway.types import (
    AgentToolSpec,
    ClaimVerification,
    DraftSnippet,
    GatewayResponse,
    ModelClassification,
    ModelGatewayError,
)
from ticket_agent.shared.settings import Settings


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "model_provider": "openai_compatible",
        "model_base_url": "https://model.example/v1",
        "model_api_key": "test-secret",
        "model_name": "ticket-classifier",
        "model_fallback_to_local": False,
        "model_data_redaction_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def _model_response(classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(classification, ensure_ascii=False),
                }
            }
        ]
    }


def test_local_draft_uses_published_product_fact() -> None:
    result = LocalModelGateway().generate_draft(
        subject="保温杯材质",
        body="这款保温杯是什么材质，能保温多久？",
        category="ecommerce_presales",
        queue_id="ECOMMERCE_PRESALES",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-product-1",
                title="316不锈钢保温杯商品知识",
                version="1.0",
                content="杯身和内胆为316不锈钢，保温约12小时。",
            )
        ],
    )

    assert "316不锈钢" in result.draft.text
    assert "12小时" in result.draft.text
    assert any(
        claim.cited_chunk_ids == ["chunk-product-1"]
        for claim in result.draft.claims
    )


def test_openai_compatible_gateway_redacts_and_validates() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "primary": "product_howto",
                    "secondary": "configuration",
                    "confidence": 0.94,
                    "risk_tags": [],
                    "summary": "客户咨询通知配置方法。",
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(_settings(), client=client).classify(
        subject="请发到 test@example.com",
        body="我的手机号 13800138000，如何配置通知？",
    )

    assert result.provider == "openai_compatible"
    assert result.classification.primary == "product_howto"
    assert captured["payload"]["max_tokens"] == 800
    messages = captured["payload"]["messages"]
    assert "<EMAIL>" in messages[1]["content"]
    assert "<MOBILE>" in messages[1]["content"]
    assert "13800138000" not in messages[1]["content"]


def test_openai_compatible_gateway_falls_back_to_local() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = OpenAICompatibleGateway(
        _settings(model_fallback_to_local=True),
        client=client,
    )
    result = gateway.classify(
        subject="如何配置企业通知",
        body="请问管理员如何为团队配置消息通知？",
    )

    assert result.fallback_used is True
    assert result.provider == "local"


def test_tool_planner_selects_only_a_supplied_tool() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "tool_id": "orders.get_order",
                    "arguments_json": "{\"order_id\":\"PDD-1001\"}",
                    "reason": "订单状态只能实时查询",
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    plan = OpenAICompatibleGateway(_settings(), client=client).plan_tool(
        query="帮我查一下订单 PDD-1001 到哪了",
        subject="物流咨询",
        skill_name="物流查询",
        skill_instructions="物流轨迹必须来自实时接口",
        tools=[
            AgentToolSpec(
                tool_id="orders.get_order",
                name="查询订单",
                description="按订单号查询",
                input_schema={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
            )
        ],
    )

    assert plan.tool_id == "orders.get_order"
    assert plan.arguments == {"order_id": "PDD-1001"}
    model_input = captured["payload"]["messages"][1]["content"]
    assert "orders.get_order" in model_input
    assert "independent human approval" in captured["payload"]["messages"][0][
        "content"
    ]


def test_tool_planner_repairs_missing_required_arguments() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        schema_name = payload["response_format"]["json_schema"]["name"]
        calls.append(schema_name)
        if schema_name == "mcp_tool_plan":
            content = {
                "tool_id": "orders.refund_order",
                "arguments_json": "{}",
                "reason": "退款操作需要人工审批",
            }
        else:
            content = {"order_id": "PDD-3003", "amount": 39.9}
        return httpx.Response(200, json=_model_response(content))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    plan = OpenAICompatibleGateway(_settings(), client=client).plan_tool(
        query="订单 PDD-3003 申请退款 39.9 元",
        subject="退款审批",
        skill_name="电商售后服务",
        skill_instructions="资金操作必须人工审批",
        tools=[
            AgentToolSpec(
                tool_id="orders.refund_order",
                name="订单退款",
                description="发起订单退款",
                input_schema={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["order_id", "amount"],
                },
                is_write=True,
            )
        ],
    )

    assert calls == ["mcp_tool_plan", "mcp_tool_arguments"]
    assert plan.arguments == {"order_id": "PDD-3003", "amount": 39.9}


def test_tool_planner_resolves_unique_short_tool_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "tool_id": "get_logistics",
                    "arguments_json": "{\"order_id\":\"PDD-MCP-2001\"}",
                    "reason": "需要查询实时物流",
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    plan = OpenAICompatibleGateway(_settings(), client=client).plan_tool(
        query="查询订单 PDD-MCP-2001 的物流",
        subject="物流查询",
        skill_name="物流专家",
        skill_instructions="必须使用实时物流工具",
        tools=[
            AgentToolSpec(
                tool_id="acceptance-mcp.get_logistics",
                name="验收物流服务 · get_logistics",
                description="查询实时物流",
                input_schema={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
            )
        ],
    )

    assert plan.tool_id == "acceptance-mcp.get_logistics"
    assert plan.arguments == {"order_id": "PDD-MCP-2001"}


def test_tool_planner_rejects_ambiguous_short_tool_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "tool_id": "get_order",
                    "arguments_json": "{}",
                    "reason": "查询订单",
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelGatewayError, match="TOOL_PLAN_UNKNOWN_TOOL"):
        OpenAICompatibleGateway(_settings(), client=client).plan_tool(
            query="查询订单",
            subject="订单查询",
            skill_name="订单专家",
            skill_instructions="查询实时订单",
            tools=[
                AgentToolSpec(
                    tool_id="orders-a.get_order",
                    name="订单服务 A",
                ),
                AgentToolSpec(
                    tool_id="orders-b.get_order",
                    name="订单服务 B",
                ),
            ],
        )


def test_tool_planner_recovers_known_id_from_malformed_suffix() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        schema_name = payload["response_format"]["json_schema"]["name"]
        calls.append(schema_name)
        if schema_name == "mcp_tool_plan":
            content = {
                "tool_id": (
                    "acceptance-mcp.get_logistics','arguments_json':'{"
                ),
                "reason": "需要查询实时物流",
            }
        else:
            content = {"order_id": "PDD-MCP-2001"}
        return httpx.Response(200, json=_model_response(content))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    plan = OpenAICompatibleGateway(_settings(), client=client).plan_tool(
        query="查询订单 PDD-MCP-2001 的实时物流",
        subject="物流查询",
        skill_name="物流专家",
        skill_instructions="必须使用实时物流工具",
        tools=[
            AgentToolSpec(
                tool_id="acceptance-mcp.get_logistics",
                name="验收物流服务 · get_logistics",
                description="查询实时物流",
                input_schema={
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                },
            )
        ],
    )

    assert calls == ["mcp_tool_plan", "mcp_tool_arguments"]
    assert plan.tool_id == "acceptance-mcp.get_logistics"
    assert plan.arguments == {"order_id": "PDD-MCP-2001"}


def test_workforce_step_generation_includes_task_context() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "summary": "需要查询订单物流状态。",
                    "findings": ["订单号 PDD-1001 已提供"],
                    "recommended_actions": ["调用物流查询工具"],
                    "requires_human": True,
                    "cited_chunk_ids": ["chunk-1"],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = OpenAICompatibleGateway(_settings(), client=client).generate_workforce_step(
        task_title="退款物流处理",
        objective="核实破损和物流状态",
        context={"order_id": "PDD-1001"},
        step_title="查询专业事实",
        instructions="查询订单物流状态",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="售后规则",
                version="1.0",
                content="物流异常需核实真实轨迹。",
            )
        ],
    )

    assert response.provider == "openai_compatible"
    prompt = captured["payload"]["messages"][1]["content"]
    assert "PDD-1001" in prompt
    assert "<context>" in prompt


def test_workforce_step_captures_inline_source_citation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "summary": (
                        "订单在运输中 [mcp:call-1]，暂无破损证据。"
                    ),
                    "findings": [],
                    "recommended_actions": [],
                    "requires_human": True,
                    "cited_chunk_ids": [],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    response = OpenAICompatibleGateway(_settings(), client=client).generate_workforce_step(
        task_title="物流事实核验",
        objective="查询订单物流",
        context={"order_id": "PDD-2001"},
        step_title="查询专业事实",
        instructions="使用实时物流结果",
        snippets=[
            DraftSnippet(
                chunk_id="mcp:call-1",
                title="MCP · 物流",
                version="live",
                content="status=IN_TRANSIT",
            )
        ],
    )

    assert response.output.cited_chunk_ids == ["mcp:call-1"]


def test_model_cannot_downgrade_security_risk() -> None:
    class UnsafeGateway:
        @property
        def name(self) -> str:
            return "unsafe-test-gateway"

        def classify(self, *, subject: str, body: str) -> GatewayResponse:
            del subject, body
            return GatewayResponse(
                classification=ModelClassification(
                    primary="product_howto",
                    secondary="configuration",
                    confidence=0.99,
                    risk_tags=[],
                    summary="普通配置咨询。",
                ),
                provider="test",
                model="unsafe-test-model",
            )

    result = MockClassifier(gateway=UnsafeGateway()).classify(
        subject="账号问题",
        body="我们的数据泄露了，请立即处理。",
        customer_tier="standard",
    )

    assert result.category_primary == "data_privacy_security"
    assert result.risk_level.value == "R3"
    assert result.needs_human is True
    assert "SECURITY_HARD_RULE" in result.reason_codes


def test_openai_compatible_generate_draft_uses_known_citation() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "text": "请按配置指南进入设置中心完成通知配置。",
                    "claims": [
                        {
                            "text": "请按配置指南进入设置中心完成通知配置。",
                            "claim_type": "instruction",
                            "cited_chunk_ids": ["chunk-1"],
                        }
                    ],
                    "cited_chunk_ids": [],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(_settings(), client=client).generate_draft(
        subject="如何配置通知",
        body="请指导配置团队通知。",
        category="product_howto",
        queue_id="PRODUCT_SUPPORT",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="企业通知配置指南",
                version="1.0",
                content="管理员进入设置中心配置团队消息通知。",
            )
        ],
    )

    assert result.draft.text == "请按配置指南进入设置中心完成通知配置。"
    assert result.draft.cited_chunk_ids == ["chunk-1"]
    assert result.draft.claims[0].claim_type == "instruction"
    assert result.provider == "openai_compatible"
    assert "企业通知配置指南" in captured["payload"]["messages"][1]["content"]


def test_employee_instructions_are_injected_as_lower_priority_block() -> None:
    systems: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        systems.append(payload["messages"][0]["content"])
        schema_name = payload["response_format"]["json_schema"]["name"]
        if schema_name == "workforce_step_output":
            content: dict[str, Any] = {
                "summary": "已核实订单状态。",
                "findings": [],
                "recommended_actions": [],
                "requires_human": False,
                "cited_chunk_ids": ["chunk-1"],
            }
        elif schema_name == "optimized_reply":
            content = {"text": "您好，订单 PDD-1001 已发货。"}
        else:
            content = {
                "text": "您好，订单 PDD-1001 已发货。",
                "claims": [
                    {
                        "text": "您好，订单 PDD-1001 已发货。",
                        "claim_type": "instruction",
                        "cited_chunk_ids": ["chunk-1"],
                    }
                ],
                "cited_chunk_ids": ["chunk-1"],
            }
        return httpx.Response(200, json=_model_response(content))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = OpenAICompatibleGateway(
        _settings(),
        client=client,
        employee_instructions="你是一名耐心、简洁的售后客服。",
    )
    snippets = [
        DraftSnippet(
            chunk_id="chunk-1",
            title="发货规则",
            version="1.0",
            content="订单发货后可在订单页查看物流。",
        )
    ]
    gateway.generate_draft(
        subject="发货咨询",
        body="我的订单发货了吗？",
        category="ecommerce_aftersales",
        queue_id="ECOMMERCE_AFTERSALES",
        snippets=snippets,
        skill_instructions="必须引用知识库",
    )
    gateway.generate_workforce_step(
        task_title="物流核实",
        objective="确认发货状态",
        context={"order_id": "PDD-1001"},
        step_title="查询事实",
        instructions="引用实时结果",
        snippets=snippets,
    )
    gateway.optimize_reply(
        text="您好，订单 PDD-1001 已发货。",
        style="concise",
    )

    assert len(systems) == 3
    for system in systems:
        assert "<employee_instructions>" in system
        assert "耐心、简洁" in system
    draft_system = systems[0]
    # 员工提示词在安全约束之后、Skill 规程之前。
    assert draft_system.index("Never invent") < draft_system.index(
        "<employee_instructions>"
    )
    assert draft_system.index("<employee_instructions>") < draft_system.index(
        "<skill_instructions>"
    )


def test_openai_compatible_rebuilds_text_from_validated_claims() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "text": "您好，下面是为您整理的说明。",
                    "claims": [
                        {
                            "text": "您好！",
                            "claim_type": "greeting",
                            "cited_chunk_ids": [],
                        },
                        {
                            "text": "保温杯内胆为 316 不锈钢。",
                            "claim_type": "instruction",
                            "cited_chunk_ids": [],
                        },
                    ],
                    "cited_chunk_ids": ["chunk-1"],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(_settings(), client=client).generate_draft(
        subject="保温杯材质",
        body="内胆是什么材质？",
        category="ecommerce_presales",
        queue_id="ECOMMERCE_PRESALES",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="保温杯参数",
                version="1.0",
                content="保温杯内胆材质为 316 不锈钢。",
            )
        ],
    )

    assert result.provider == "openai_compatible"
    assert result.draft.text == "您好！\n保温杯内胆为 316 不锈钢。"
    assert result.draft.cited_chunk_ids == ["chunk-1"]


def test_openai_compatible_optimizes_reply_without_changing_numbers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        prompt = json.dumps(payload["messages"], ensure_ascii=False)
        assert "professional" in prompt
        assert "480ml" in prompt
        return httpx.Response(
            200,
            json=_model_response(
                {"text": "您好，这款保温杯容量为 480ml，请核对后回复。"}
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    optimized = OpenAICompatibleGateway(
        _settings(),
        client=client,
    ).optimize_reply(
        text="你好，这个杯子的容量是480ml，请确认。",
        style="professional",
    )

    assert "480ml" in optimized


def test_reply_optimization_rejects_changed_numeric_commitment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {"text": "您好，我们将在 3 个工作日内完成处理。"}
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ModelGatewayError):
        OpenAICompatibleGateway(
            _settings(),
            client=client,
        ).optimize_reply(
            text="您好，我们将在 5 个工作日内完成处理。",
            style="concise",
        )


def test_draft_with_unsupported_numeric_commitment_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "text": "我们承诺在 3 个工作日内完成退款。",
                    "claims": [
                        {
                            "text": "我们承诺在 3 个工作日内完成退款。",
                            "claim_type": "policy",
                            "cited_chunk_ids": ["chunk-1"],
                        }
                    ],
                    "cited_chunk_ids": ["chunk-1"],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(
        _settings(model_fallback_to_local=True),
        client=client,
    ).generate_draft(
        subject="退款处理",
        body="什么时候可以退款？",
        category="transaction_dispute",
        queue_id="TRANSACTION_OPS",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="退款流程",
                version="1.0",
                content="退款申请需要人工审核，具体时效以客服确认为准。",
            )
        ],
    )

    assert result.fallback_used is True
    assert result.provider == "local"
    assert "3 个工作日" not in result.draft.text


def test_policy_claim_without_sentence_citation_falls_back() -> None:
    text = "您好。请进入设置中心。退款将在审核后处理。"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "text": text,
                    "claims": [
                        {
                            "text": "您好。",
                            "claim_type": "greeting",
                            "cited_chunk_ids": [],
                        },
                        {
                            "text": "请进入设置中心。",
                            "claim_type": "instruction",
                            "cited_chunk_ids": ["chunk-1"],
                        },
                        {
                            "text": "退款将在审核后处理。",
                            "claim_type": "policy",
                            "cited_chunk_ids": [],
                        },
                    ],
                    "cited_chunk_ids": ["chunk-1"],
                }
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(
        _settings(model_fallback_to_local=True),
        client=client,
    ).generate_draft(
        subject="退款",
        body="什么时候退款？",
        category="transaction_dispute",
        queue_id="TRANSACTION_OPS",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="退款流程",
                version="1.0",
                content="请进入设置中心查看退款状态。",
            )
        ],
    )

    assert result.fallback_used is True
    assert result.provider == "local"


def test_enforced_semantic_verifier_rejects_unsupported_draft() -> None:
    text = "请进入设置中心。配置会自动生效。"

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_model_response(
                {
                    "text": text,
                    "claims": [
                        {
                            "text": "请进入设置中心。",
                            "claim_type": "instruction",
                            "cited_chunk_ids": ["chunk-1"],
                        },
                        {
                            "text": "配置会自动生效。",
                            "claim_type": "policy",
                            "cited_chunk_ids": ["chunk-1"],
                        },
                    ],
                    "cited_chunk_ids": ["chunk-1"],
                }
            ),
        )

    class RejectingVerifier:
        name = "rejecting-judge"
        enforce = True

        def verify(self, claims: list[ClaimToVerify]) -> list[ClaimVerification]:
            return [
                ClaimVerification(
                    claim_index=claim.claim_index,
                    verdict="unsupported",
                    confidence=0.99,
                    reason="Sources do not entail auto activation.",
                    provider="test",
                    model=self.name,
                )
                for claim in claims
            ]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OpenAICompatibleGateway(
        _settings(model_fallback_to_local=True),
        client=client,
        claim_verifier=RejectingVerifier(),
    ).generate_draft(
        subject="配置通知",
        body="配置后会立即生效吗？",
        category="product_howto",
        queue_id="PRODUCT_SUPPORT",
        snippets=[
            DraftSnippet(
                chunk_id="chunk-1",
                title="通知配置",
                version="1.0",
                content="进入设置中心配置通知，生效时间以页面提示为准。",
            )
        ],
    )

    assert result.fallback_used is True
    assert result.provider == "local"

