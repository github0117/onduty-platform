import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge import service as knowledge_service_module
from ticket_agent.knowledge.claim_verifier import ClaimToVerify, ExternalClaimVerifier
from ticket_agent.knowledge.local_embedding import LocalEmbeddingProvider
from ticket_agent.knowledge.openai_embedding import OpenAICompatibleEmbeddingProvider
from ticket_agent.knowledge.rerank import ExternalHTTPReranker
from ticket_agent.knowledge.retrieval import RetrievalCandidate
from ticket_agent.knowledge.schemas import KnowledgeDocumentCreate, KnowledgeVersionCreate
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.model_gateway import usage as usage_module
from ticket_agent.model_gateway.models import ModelCall
from ticket_agent.model_gateway.types import ModelGatewayError
from ticket_agent.model_gateway.usage import ModelUsageGuard, ModelUsageService
from ticket_agent.shared.db import SessionLocal
from ticket_agent.shared.settings import Settings


def _employee(budgets: dict[str, object] | None = None) -> DigitalEmployee:
    return DigitalEmployee(
        id=uuid4(),
        employee_key="usage_employee",
        name="用量测试员工",
        version="1.0.0",
        scenario_type="test",
        workflow_key="customer_service_ticket_v1",
        business_unit_id="bu_test",
        service_identity="digital_employee.usage",
        status="ACTIVE",
        handoff_queue="TEST",
        knowledge_policy_json={},
        model_profile_json={"budgets": budgets or {}},
        tool_allowlist_json=[],
        created_by="test",
    )


def test_model_usage_records_tokens_and_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        usage_module,
        "get_settings",
        lambda: Settings(
            model_input_cost_per_1k_tokens=1.0,
            model_output_cost_per_1k_tokens=2.0,
        ),
    )
    employee = _employee()
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="usage-test",
        )
        started = guard.start(purpose="classification")
        guard.succeed(
            purpose="classification",
            provider="openai_compatible",
            model_name="classifier",
            usage=usage_module.TokenUsage(input_tokens=1000, output_tokens=500),
            started_monotonic=started,
        )
        session.commit()
        call = session.scalar(select(ModelCall))

    assert call is not None
    assert call.total_tokens == 1500
    assert call.estimated_cost == 2.0
    assert call.status == "SUCCEEDED"


def test_model_budget_denial_is_recorded() -> None:
    employee = _employee({"monthly_calls": 0})
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="budget-denied",
        )
        with pytest.raises(ModelGatewayError):
            guard.start(purpose="generation")
        session.commit()
        call = session.scalar(select(ModelCall))

    assert call is not None
    assert call.status == "DENIED"
    assert call.error_code == "MODEL_BUDGET_EXCEEDED"


def test_daily_model_budget_denial_is_recorded() -> None:
    employee = _employee({"daily_calls": 0})
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="daily-budget-denied",
        )
        with pytest.raises(ModelGatewayError, match="daily_calls"):
            guard.start(purpose="generation")
        session.commit()
        call = session.scalar(select(ModelCall))

    assert call is not None
    assert call.status == "DENIED"
    assert call.error_code == "MODEL_BUDGET_EXCEEDED"


def test_daily_budget_status_forecasts_limit_breach() -> None:
    employee = _employee({"daily_calls": 10, "weekly_cost": 2})
    now = datetime(2026, 10, 23, 1, 0, tzinfo=UTC)
    with SessionLocal() as session:
        session.add(
            ModelCall(
                employee_id=employee.id,
                business_unit_id=employee.business_unit_id,
                correlation_id="daily-budget-forecast",
                purpose="classification",
                provider="openai_compatible",
                model_name="classifier",
                status="SUCCEEDED",
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                estimated_cost=0.01,
                latency_ms=100,
                started_at=now,
                completed_at=now,
            )
        )
        session.flush()
        status = ModelUsageService(session).budget_status(employee, now=now)

    daily = next(period for period in status["periods"] if period["period"] == "daily")
    assert status["forecast_alert"] is True
    assert status["exceeded"] is False
    assert daily["projected"]["calls"] == 24.0
    assert "DAILY_CALLS_FORECAST" in daily["alerts"]


def test_claim_judge_usage_is_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verifications": [
                                        {
                                            "claim_index": 0,
                                            "verdict": "supported",
                                            "confidence": 0.9,
                                            "reason": "supported",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 20},
            },
        )

    employee = _employee()
    settings = Settings(
        claim_verifier_provider="external",
        claim_verifier_base_url="https://judge.example/v1",
        claim_verifier_model_name="judge",
        claim_verifier_fallback_to_local=False,
    )
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="judge-usage",
        )
        verifier = ExternalClaimVerifier(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            usage_guard=guard,
        )
        verifier.verify(
            [
                ClaimToVerify(
                    claim_index=0,
                    text="policy",
                    claim_type="policy",
                    sources=["source"],
                )
            ]
        )
        session.commit()
        call = session.scalar(
            select(ModelCall).where(ModelCall.purpose == "claim_verification")
        )

    assert call is not None
    assert call.total_tokens == 100
    assert call.status == "SUCCEEDED"


def test_external_rerank_usage_is_recorded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "results": [{"index": 0, "relevance_score": 0.9}],
                "usage": {"prompt_tokens": 60, "completion_tokens": 10},
            },
        )

    employee = _employee()
    settings = Settings(
        rerank_base_url="https://rerank.example/v1",
        rerank_model_name="reranker",
        rerank_fallback_to_local=False,
    )
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="rerank-usage",
        )
        reranker = ExternalHTTPReranker(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            usage_guard=guard,
        )
        reranker.rerank(
            query="query",
            candidates=[
                RetrievalCandidate(
                    chunk_id=uuid4(),
                    document_id=uuid4(),
                    title="doc",
                    version="1.0",
                    content="content",
                    vector_score=0.8,
                )
            ],
            top_k=1,
        )
        session.commit()
        call = session.scalar(select(ModelCall).where(ModelCall.purpose == "rerank"))

    assert call is not None
    assert call.total_tokens == 70
    assert call.status == "SUCCEEDED"


def test_system_embedding_usage_is_recorded_for_business_unit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [1.0, 0.0, 0.0]}],
                "usage": {"prompt_tokens": 42},
            },
        )

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model_name="embedding-model",
        embedding_dimensions=3,
        embedding_fallback_to_local=False,
    )
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=None,
            business_unit_id="bu_knowledge",
            ticket_id=None,
            correlation_id="embedding-system-usage",
        )
        provider = OpenAICompatibleEmbeddingProvider(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            usage_guard=guard,
        )
        assert provider.embed_texts(["policy"]) == [[1.0, 0.0, 0.0]]
        session.commit()
        call = session.scalar(select(ModelCall))

    assert call is not None
    assert call.employee_id is None
    assert call.business_unit_id == "bu_knowledge"
    assert call.purpose == "embedding"
    assert call.total_tokens == 42
    assert call.status == "SUCCEEDED"


def test_knowledge_ingestion_uses_system_embedding_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [1.0, 0.0, 0.0]}],
                "usage": {"prompt_tokens": 31},
            },
        )

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model_name="ingestion-embedding",
        embedding_dimensions=3,
        embedding_fallback_to_local=False,
    )

    def provider_factory(
        usage_guard: ModelUsageGuard | None = None,
    ) -> OpenAICompatibleEmbeddingProvider | LocalEmbeddingProvider:
        if usage_guard is None:
            return LocalEmbeddingProvider(3)
        return OpenAICompatibleEmbeddingProvider(
            settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            usage_guard=usage_guard,
        )

    monkeypatch.setattr(
        knowledge_service_module,
        "get_embedding_provider",
        provider_factory,
    )
    with SessionLocal() as session:
        service = KnowledgeService(session)
        document = service.create_document(
            KnowledgeDocumentCreate(
                business_unit_id="bu_knowledge",
                title="Embedding 审计指引",
                doc_type="SOP",
                owner_id="knowledge-owner",
                scope={},
            ),
            actor_id="knowledge-owner",
        )
        version = service.create_version(
            document.id,
            KnowledgeVersionCreate(
                version_label="1.0",
                content="知识入库调用需要记录业务单元和 Embedding Token 用量。",
            ),
            correlation_id="knowledge-ingestion-usage",
        )
        call = session.scalar(select(ModelCall))

    assert call is not None
    assert call.employee_id is None
    assert call.business_unit_id == "bu_knowledge"
    assert call.correlation_id == "knowledge-ingestion-usage"
    assert call.purpose == "embedding"
    assert call.total_tokens == 31
    assert version.embedding_model == "openai-compatible:ingestion-embedding"


def test_embedding_budget_denial_falls_back_to_local() -> None:
    employee = _employee({"monthly_calls": 0})
    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_base_url="https://embedding.example/v1",
        embedding_model_name="embedding-model",
        embedding_dimensions=8,
        embedding_fallback_to_local=True,
    )
    with SessionLocal() as session:
        guard = ModelUsageGuard(
            session,
            employee=employee,
            ticket_id=None,
            correlation_id="embedding-budget-denied",
        )
        provider = OpenAICompatibleEmbeddingProvider(settings, usage_guard=guard)
        embedding = provider.embed_texts(["budget fallback"])[0]
        session.commit()
        call = session.scalar(select(ModelCall))

    assert len(embedding) == 8
    assert call is not None
    assert call.status == "DENIED"
    assert call.error_code == "MODEL_BUDGET_EXCEEDED"

