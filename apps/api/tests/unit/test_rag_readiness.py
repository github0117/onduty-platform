from typing import Any, cast

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ticket_agent import main
from ticket_agent.knowledge.readiness import rag_readiness_issues
from ticket_agent.shared.settings import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "app_auth_mode": "oidc",
        "oidc_issuer_url": "https://issuer.example",
        "oidc_audience": "ticket-agent",
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "https://embedding.example/v1",
        "embedding_api_key": "test-only-key",
        "embedding_model_name": "text-embedding-v3",
        "knowledge_retrieval_mode": "hybrid",
        "knowledge_rerank_provider": "external",
        "rerank_base_url": "https://rerank.example/v1",
        "rerank_model_name": "rerank-model",
    }
    values.update(overrides)
    return Settings(**values)


def test_development_accepts_demo_rag_configuration() -> None:
    settings = Settings(app_env="development", app_auth_mode="dev")

    assert rag_readiness_issues(settings) == []


def test_production_accepts_semantic_hybrid_remote_rerank() -> None:
    assert rag_readiness_issues(production_settings()) == []


def test_production_rejects_local_hash_embeddings() -> None:
    issues = rag_readiness_issues(
        production_settings(embedding_provider="local")
    )

    assert len(issues) == 1
    assert "embedding" in issues[0]


def test_production_rejects_remote_embedding_without_key() -> None:
    issues = rag_readiness_issues(
        production_settings(embedding_api_key="")
    )

    assert "embedding" in issues[0]


def test_production_requires_hybrid_retrieval() -> None:
    issues = rag_readiness_issues(
        production_settings(knowledge_retrieval_mode="dense")
    )

    assert any("hybrid" in issue for issue in issues)


def test_production_requires_remote_reranker() -> None:
    issues = rag_readiness_issues(
        production_settings(knowledge_rerank_provider="local")
    )

    assert any("rerank" in issue for issue in issues)


def test_production_rejects_external_reranker_without_endpoint() -> None:
    issues = rag_readiness_issues(
        production_settings(rerank_base_url="")
    )

    assert any("rerank" in issue for issue in issues)


def test_production_accepts_dashscope_reranker_with_model_credentials() -> None:
    settings = production_settings(
        knowledge_rerank_provider="dashscope",
        rerank_base_url="",
        rerank_api_key="",
        model_api_key="test-only-key",
    )

    assert rag_readiness_issues(settings) == []


def test_health_ready_returns_503_for_demo_rag_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        production_settings(embedding_provider="local"),
    )

    with pytest.raises(HTTPException) as exc_info:
        main.health_ready()

    assert exc_info.value.status_code == 503
    detail = cast(dict[str, Any], exc_info.value.detail)
    assert detail["status"] == "not_ready"
    assert "embedding" in detail["issues"][0]


def test_health_ready_returns_ok_for_complete_production_rag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "settings", production_settings())

    response = main.health_ready()

    assert response.status == "ok"
    assert response.environment == "production"


def test_health_ready_endpoint_returns_503_for_demo_rag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "settings",
        production_settings(embedding_provider="local"),
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "not_ready"
    assert detail["database"] == "ok"
    assert "embedding" in detail["issues"][0]


def test_health_ready_endpoint_returns_200_for_complete_rag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "settings", production_settings())

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["environment"] == "production"
