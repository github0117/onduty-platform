from uuid import uuid4

import httpx
import pytest

from ticket_agent.customer_service.context import load_memory
from ticket_agent.customer_service.models import ConversationMemory, CustomerConversation
from ticket_agent.customer_service.service import CustomerConversationService
from ticket_agent.model_gateway.local import LocalModelGateway
from ticket_agent.model_gateway.openai_compatible import OpenAICompatibleGateway
from ticket_agent.model_gateway.types import ModelGatewayError
from ticket_agent.shared.db import system_session
from ticket_agent.shared.settings import Settings


class _FakeGateway:
    def __init__(
        self,
        *,
        summary: str = "用户订单 AB-1001 未发货，已转人工并承诺 24 小时内回复。",
        error: Exception | None = None,
    ) -> None:
        self.summary = summary
        self.error = error
        self.calls: list[dict[str, object]] = []

    def summarize_conversation(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.summary


def _conversation(session, requester: str) -> CustomerConversation:
    conversation = CustomerConversation(
        id=uuid4(),
        business_unit_id="bu_demo",
        requester_ref=requester,
        status="ACTIVE",
    )
    session.add(conversation)
    session.flush()
    return conversation


def test_local_summary_is_capped() -> None:
    result = LocalModelGateway().summarize_conversation(
        previous_summary="旧摘要",
        turns=[("买家", "订单 AB-1001 一直没发货")],
        max_chars=10,
        timeout_seconds=8.0,
    )

    assert len(result) == 10
    assert result.endswith("一直没发货")


def test_summary_is_skipped_below_thresholds(monkeypatch) -> None:
    fake = _FakeGateway()
    monkeypatch.setattr(
        "ticket_agent.customer_service.service.get_model_gateway",
        lambda: fake,
    )

    with system_session() as session:
        conversation = _conversation(session, "summary-below-threshold")
        service = CustomerConversationService(session)
        for sequence in range(1, 6):
            service._update_memory(
                conversation.id,
                sequence,
                f"问题 {sequence}",
                f"回复 {sequence}",
            )

        memory = session.get(ConversationMemory, conversation.id)

    assert fake.calls == []
    assert memory is not None
    assert memory.summarized_through_sequence == 0
    assert "第 5 轮" in memory.summary


def test_summary_runs_on_sixth_turn(monkeypatch) -> None:
    fake = _FakeGateway()
    monkeypatch.setattr(
        "ticket_agent.customer_service.service.get_model_gateway",
        lambda: fake,
    )

    with system_session() as session:
        conversation = _conversation(session, "summary-six-turns")
        service = CustomerConversationService(session)
        for sequence in range(1, 7):
            service._update_memory(
                conversation.id,
                sequence,
                "订单 AB-1001 一直没发货",
                "已为您转人工跟进，预计 24 小时内回复。",
            )
        session.commit()
        memory = session.get(ConversationMemory, conversation.id)
        snapshot = load_memory(session, conversation.id)

    assert len(fake.calls) == 1
    assert fake.calls[0]["max_chars"] == 400
    assert fake.calls[0]["timeout_seconds"] == 8.0
    assert memory is not None
    assert memory.summarized_through_sequence == 6
    assert memory.summary == fake.summary
    assert snapshot is not None
    assert snapshot.summary == fake.summary


def test_summary_failure_keeps_truncated_summary(monkeypatch) -> None:
    fake = _FakeGateway(error=RuntimeError("timeout"))
    monkeypatch.setattr(
        "ticket_agent.customer_service.service.get_model_gateway",
        lambda: fake,
    )

    with system_session() as session:
        conversation = _conversation(session, "summary-failure")
        service = CustomerConversationService(session)
        for sequence in range(1, 7):
            service._update_memory(
                conversation.id,
                sequence,
                "订单 AB-1001 一直没发货",
                "已为您转人工跟进。",
            )
        session.commit()
        memory = session.get(ConversationMemory, conversation.id)

    assert len(fake.calls) == 1
    assert memory is not None
    assert memory.summarized_through_sequence == 0
    assert "第 6 轮" in memory.summary


def test_remote_summary_uses_eight_second_timeout_without_retry() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="https://example.test/v1",
        model_name="summary-model",
    )
    gateway = OpenAICompatibleGateway(
        settings,
        use_configured_claim_verifier=False,
    )
    calls: list[float | None] = []

    def fake_post(url, *, headers, json, timeout):
        del url, headers, json
        calls.append(timeout)
        return httpx.Response(500)

    gateway._client.post = fake_post  # type: ignore[method-assign]

    with pytest.raises(ModelGatewayError):
        gateway.summarize_conversation(
            previous_summary="旧摘要",
            turns=[("买家", "订单 AB-1001 未发货")],
            max_chars=400,
            timeout_seconds=8.0,
        )

    assert calls == [8.0]


def test_remote_summary_parses_json_content() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="https://example.test/v1",
        model_name="summary-model",
    )
    gateway = OpenAICompatibleGateway(
        settings,
        use_configured_claim_verifier=False,
    )
    payloads: list[dict[str, object]] = []

    def fake_post(url, *, headers, json, timeout):
        del url, headers, timeout
        payloads.append(json)
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.test/v1"),
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary": "订单 AB-1001 已转人工"}'
                        }
                    }
                ]
            },
        )

    gateway._client.post = fake_post  # type: ignore[method-assign]

    summary = gateway.summarize_conversation(
        previous_summary="",
        turns=[("买家", "订单 AB-1001 未发货")],
        max_chars=400,
        timeout_seconds=8.0,
    )

    assert summary == "订单 AB-1001 已转人工"
    # DashScope qwen-plus degrades with strict json_schema on long prompts,
    # so the summary path must request plain text.
    assert "response_format" not in payloads[0]


def test_remote_summary_accepts_plain_text() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="https://example.test/v1",
        model_name="summary-model",
    )
    gateway = OpenAICompatibleGateway(
        settings,
        use_configured_claim_verifier=False,
    )

    def fake_post(url, *, headers, json, timeout):
        del url, headers, json, timeout
        return httpx.Response(
            200,
            request=httpx.Request("POST", "https://example.test/v1"),
            json={
                "choices": [
                    {"message": {"content": "订单 AB-1001 未发货，已转人工跟进。"}}
                ]
            },
        )

    gateway._client.post = fake_post  # type: ignore[method-assign]

    summary = gateway.summarize_conversation(
        previous_summary="历史摘要",
        turns=[("买家", "订单 AB-1001 未发货")],
        max_chars=400,
        timeout_seconds=8.0,
    )

    assert summary == "订单 AB-1001 未发货，已转人工跟进。"
