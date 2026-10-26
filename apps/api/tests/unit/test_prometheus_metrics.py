import re

import pytest

from ticket_agent.observability.exporter import (
    authorize_metrics,
    render_labeled_prometheus_metrics,
    render_prometheus_metrics,
)
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


def test_render_prometheus_metrics() -> None:
    rendered = render_prometheus_metrics(
        sync={
            "attempted": 10,
            "pending": 1,
            "syncing": 1,
            "retrying": 2,
            "succeeded": 5,
            "failed": 1,
            "success_rate": 0.833,
            "failure_rate": 0.167,
            "average_attempts": 1.3,
        },
        rag={
            "draft_count": 8,
            "grounded_count": 7,
            "grounding_rate": 0.875,
            "policy_citation_coverage": 1.0,
            "semantic_verified_claim_count": 12,
            "semantic_unsupported_claim_count": 0,
        },
    )

    assert "ticket_worker_sync_failure_rate 0.167" in rendered
    assert "ticket_worker_rag_grounding_rate 0.875" in rendered
    assert "ticket_worker_rag_semantic_unsupported_claims 0" in rendered
    assert (
        "# TYPE ticket_worker_rate_limit_rejections_total counter" in rendered
    )
    assert re.search(
        r"^ticket_worker_rate_limit_rejections_total \d+$",
        rendered,
        flags=re.MULTILINE,
    )


def test_metrics_bearer_token_validation() -> None:
    settings = Settings(
        app_env="production",
        app_auth_mode="oidc",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="ticket-agent",
        metrics_scrape_token="secret",
    )

    authorize_metrics("Bearer secret", settings)
    with pytest.raises(ApiProblem) as error:
        authorize_metrics("Bearer wrong", settings)
    assert error.value.status_code == 401


def test_production_requires_metrics_token() -> None:
    with pytest.raises(ApiProblem) as error:
        authorize_metrics(
            None,
            Settings(
                app_env="production",
                app_auth_mode="oidc",
                oidc_issuer_url="https://issuer.example",
                oidc_audience="ticket-agent",
            ),
        )

    assert error.value.status_code == 503


def test_render_labeled_metrics_groups_by_business_unit() -> None:
    sync = {
        "attempted": 2,
        "pending": 0,
        "syncing": 0,
        "retrying": 1,
        "succeeded": 1,
        "failed": 0,
        "success_rate": 1.0,
        "failure_rate": 0.0,
        "average_attempts": 1.0,
    }
    rag = {
        "draft_count": 2,
        "grounded_count": 1,
        "grounding_rate": 0.5,
        "policy_citation_coverage": 1.0,
        "semantic_verified_claim_count": 1,
        "semantic_unsupported_claim_count": 0,
    }
    tools = {
        "calls": 4,
        "succeeded": 3,
        "failed": 1,
        "denied": 0,
        "success_rate": 0.75,
        "failure_rate": 0.25,
        "average_duration_ms": 120.0,
        "p95_duration_ms": 250.0,
    }
    models = {
        "calls": 5,
        "succeeded": 4,
        "failed": 0,
        "denied": 1,
        "input_tokens": 1200,
        "output_tokens": 400,
        "total_tokens": 1600,
        "estimated_cost": 0.03,
        "budget_exceeded": 0,
        "budget_forecast_alerts": 1,
    }
    rendered = render_labeled_prometheus_metrics(
        [
            (
                {"business_unit": "sales", "adapter": "http_json"},
                sync,
                rag,
                tools,
                models,
            ),
            (
                {"business_unit": "support", "adapter": "http_json"},
                sync,
                rag,
                tools,
                models,
            ),
        ]
    )

    assert rendered.count("# HELP ticket_worker_sync_attempted") == 1
    assert 'business_unit="sales"' in rendered
    assert 'business_unit="support"' in rendered
    assert "ticket_worker_tool_p95_duration_ms" in rendered
    assert "ticket_worker_model_total_tokens" in rendered
    assert "ticket_worker_model_estimated_cost" in rendered
    assert "ticket_worker_model_budget_forecast_alerts" in rendered

