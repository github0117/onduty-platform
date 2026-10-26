from uuid import uuid4

import pytest
from sqlalchemy import select

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.retrieval import HybridReranker
from ticket_agent.model_gateway.openai_compatible import OpenAICompatibleGateway
from ticket_agent.model_gateway.profile import (
    build_classifier_for_employee,
    build_draft_service_for_employee,
    build_reranker_for_employee,
    resolve_model_profile,
)
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings
from ticket_agent.tools.execution import ToolExecutionService
from ticket_agent.tools.models import ToolCall
from ticket_agent.tools.registry import ToolPermissionError, tool_registry
from ticket_agent.workflow.profile import resolve_knowledge_options


def _employee(
    tools: list[str],
    *,
    model_profile: dict[str, object] | None = None,
) -> DigitalEmployee:
    return DigitalEmployee(
        id=uuid4(),
        employee_key="test_employee",
        name="测试数字员工",
        version="1.0.0",
        scenario_type="test",
        workflow_key="customer_service_ticket_v1",
        business_unit_id="bu_test",
        service_identity="digital_employee.test",
        status="ACTIVE",
        handoff_queue="TEST_QUEUE",
        knowledge_policy_json={},
        model_profile_json=model_profile
        or {"knowledge": {"top_k": 3, "min_score": 0.25}},
        tool_allowlist_json=tools,
        created_by="test",
    )


def test_tool_registry_enforces_allowlist_and_human_approval() -> None:
    employee = _employee(["knowledge.search", "ticket.sync"])

    assert tool_registry.authorize(employee, "knowledge.search").key == "knowledge.search"
    with pytest.raises(ToolPermissionError):
        tool_registry.authorize(employee, "draft.create")
    with pytest.raises(ToolPermissionError):
        tool_registry.authorize(employee, "ticket.sync")
    assert tool_registry.authorize(
        employee,
        "ticket.sync",
        human_approved=True,
    ).risk_level == "R2"


def test_employee_knowledge_profile_is_validated() -> None:
    options = resolve_knowledge_options(_employee([]))

    assert options.top_k == 3
    assert options.min_score == 0.25


def test_unregistered_tool_is_rejected() -> None:
    with pytest.raises(ToolPermissionError):
        tool_registry.authorize(_employee(["unknown.tool"]), "unknown.tool")


def test_employee_profile_overrides_classification_threshold() -> None:
    employee = _employee(
        ["ticket.read", "knowledge.search", "draft.create"],
        model_profile={
            "classification": {
                "provider": "local",
                "confidence_threshold": 0.99,
            }
        },
    )
    profile = resolve_model_profile(employee)
    classifier = build_classifier_for_employee(employee)
    result = classifier.classify(
        subject="如何配置团队通知",
        body="管理员如何配置团队消息通知？",
        customer_tier="standard",
    )

    assert profile.classification.confidence_threshold == 0.99
    assert result.needs_human is True
    assert result.human_reason == "LOW_CLASSIFICATION_CONFIDENCE"


def test_employee_profile_overrides_rerank_weights() -> None:
    employee = _employee(
        ["ticket.read"],
        model_profile={
            "rerank": {
                "provider": "local",
                "vector_weight": 0.4,
                "lexical_weight": 0.6,
            }
        },
    )

    reranker = build_reranker_for_employee(employee)

    assert isinstance(reranker, HybridReranker)
    assert reranker.vector_weight == 0.4
    assert reranker.lexical_weight == 0.6


def test_employee_generation_inherits_global_openai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="https://model.example/v1",
        model_api_key="test-key",
        model_name="qwen-test",
    )
    monkeypatch.setattr(
        "ticket_agent.model_gateway.profile.get_settings",
        lambda: settings,
    )

    service = build_draft_service_for_employee(_employee([]))

    assert isinstance(service.gateway, OpenAICompatibleGateway)


def test_invalid_tool_payload_creates_failed_call() -> None:
    employee = _employee(["knowledge.search"])
    with SessionLocal() as session:
        service = ToolExecutionService(session)
        with pytest.raises(ApiProblem) as error:
            service.begin(
                employee=employee,
                tool_key="knowledge.search",
                payload={
                    "query": "",
                    "business_unit_id": "bu_test",
                    "scope": {},
                },
                correlation_id="schema-failure",
            )
        session.commit()
        call = session.scalar(select(ToolCall))

    assert error.value.code == "TOOL_SCHEMA_VALIDATION_FAILED"
    assert call is not None
    assert call.status == "FAILED"
    assert call.error_code == "TOOL_SCHEMA_VALIDATION_FAILED"

