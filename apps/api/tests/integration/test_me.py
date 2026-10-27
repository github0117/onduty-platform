from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ticket_agent.identity.models import Principal


def _headers(role: str, **extra: str) -> dict[str, str]:
    return {
        "X-Actor-Id": f"{role}-1",
        "X-Actor-Role": role,
        **extra,
    }


def test_me_returns_dev_identity_and_capabilities(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me",
        headers=_headers(
            "admin",
            **{"X-Business-Unit-Id": "bu_demo", "X-Business-Units": "bu_demo,bu_acceptance"},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["actor_id"] == "admin-1"
    assert body["role"] == "admin"
    assert body["role_label"] == "平台管理员"
    assert body["issuer"] == "dev"
    assert body["auth_mode"] == "dev"
    assert body["test_identity_switch_enabled"] is True
    assert body["business_units"] == ["bu_demo", "bu_acceptance"]
    assert body["business_unit_labels"]["bu_acceptance"] == (
        "隔离验真租户（无演示数据）"
    )
    assert body["primary_business_unit_id"] == "bu_demo"
    assert body["active_business_unit_id"] == "bu_demo"
    assert "demo.reset" in body["capabilities"]
    assert "tickets.write" in body["capabilities"]
    assert body["features"]["demo_reset"]["enabled"] is True
    assert body["features"]["demo_reset"]["reason"] is None


def test_me_is_role_authoritative(client: TestClient) -> None:
    agent = client.get("/api/v1/me", headers=_headers("agent")).json()
    assert "tickets.write" in agent["capabilities"]
    assert "operations.view" not in agent["capabilities"]
    assert "service.admin" not in agent["capabilities"]
    assert agent["features"]["demo_reset"]["enabled"] is False
    assert agent["features"]["demo_reset"]["reason"] == "role_not_permitted"

    auditor = client.get("/api/v1/me", headers=_headers("auditor")).json()
    assert "operation" not in auditor["role"]
    assert "tickets.write" not in auditor["capabilities"]
    assert "service.approvals.view" in auditor["capabilities"]
    assert "service.approvals.decide" not in auditor["capabilities"]


def test_me_normalizes_unknown_role_to_requester(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me",
        headers={"X-Actor-Id": "unknown-1", "X-Actor-Role": "root"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "requester"
    assert body["capabilities"] == ["tickets.view_self"]


def test_me_rejects_foreign_business_unit_query(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me?business_unit_id=bu_other",
        headers=_headers("admin", **{"X-Business-Unit-Id": "bu_demo"}),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "BUSINESS_UNIT_ACCESS_DENIED"


def test_me_disables_demo_reset_outside_demo_tenant(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me?business_unit_id=bu_acceptance",
        headers=_headers(
            "admin",
            **{"X-Business-Unit-Id": "bu_demo", "X-Business-Units": "bu_demo,bu_acceptance"},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["active_business_unit_id"] == "bu_acceptance"
    assert body["features"]["demo_reset"]["enabled"] is False
    assert body["features"]["demo_reset"]["reason"] == (
        "active_business_unit_not_demo"
    )
    assert body["features"]["demo_reset"]["active_business_unit_eligible"] is False


def test_me_disables_demo_reset_when_setting_is_off(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ticket_agent.identity.policy.get_settings",
        lambda: SimpleNamespace(
            demo_reset_enabled=False,
            app_env="test",
            app_auth_mode="dev",
        ),
    )

    body = client.get("/api/v1/me", headers=_headers("admin")).json()

    assert body["features"]["demo_reset"]["enabled"] is False
    assert body["features"]["demo_reset"]["reason"] == "disabled_by_settings"


def test_me_uses_oidc_claims_without_test_switching(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oidc_settings = SimpleNamespace(
        app_auth_mode="oidc",
        app_env="test",
        demo_reset_enabled=True,
    )

    class _Authenticator:
        def authenticate(self, token: str) -> Principal:
            assert token == "oidc-token"
            return Principal(
                actor_id="oidc.agent",
                role="agent",
                service_identity="digital_agent.ticket.v1",
                issuer="https://issuer.example",
                business_units=("bu_demo", "bu_acceptance"),
            )

    monkeypatch.setattr(
        "ticket_agent.identity.dependencies.get_settings",
        lambda: oidc_settings,
    )
    monkeypatch.setattr(
        "ticket_agent.identity.dependencies.get_oidc_authenticator",
        lambda: _Authenticator(),
    )
    monkeypatch.setattr(
        "ticket_agent.identity.router.get_settings",
        lambda: oidc_settings,
    )
    monkeypatch.setattr(
        "ticket_agent.identity.policy.get_settings",
        lambda: oidc_settings,
    )

    response = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer oidc-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["auth_mode"] == "oidc"
    assert body["issuer"] == "https://issuer.example"
    assert body["test_identity_switch_enabled"] is False
    assert body["actor_id"] == "oidc.agent"
    assert body["business_units"] == ["bu_demo", "bu_acceptance"]


def test_me_requires_bearer_in_oidc_mode(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ticket_agent.identity.dependencies.get_settings",
        lambda: SimpleNamespace(app_auth_mode="oidc"),
    )

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
