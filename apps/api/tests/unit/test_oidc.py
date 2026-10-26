import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ticket_agent.identity.dependencies import get_principal
from ticket_agent.identity.oidc import OIDCAuthenticator, resolve_role
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings


def _auth_fixture() -> tuple[OIDCAuthenticator, Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(),
        as_dict=True,
    )
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    settings = Settings(
        app_auth_mode="oidc",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="ticket-agent",
        oidc_jwks_url="https://issuer.example/jwks",
        oidc_roles_claim="roles",
    )
    return OIDCAuthenticator(settings), private_key, public_jwk


def _token(private_key: Any, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "user-123",
        "iss": "https://issuer.example",
        "aud": "ticket-agent",
        "iat": now,
        "exp": now + 300,
        "roles": ["support-agent"],
        "customer_ref": "customer-123",
        "business_units": ["bu_demo", "bu_second"],
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_oidc_validates_signature_and_builds_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )

    principal = authenticator.authenticate(_token(private_key))

    assert principal.actor_id == "user-123"
    assert principal.customer_ref == "customer-123"
    assert principal.role == "agent"
    assert principal.issuer == "https://issuer.example"
    assert principal.service_identity == "human.oidc"
    assert principal.business_units == ("bu_demo", "bu_second")
    assert principal.primary_business_unit_id == "bu_demo"


def test_oidc_requires_business_unit_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )
    token = _token(private_key)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims.pop("business_units")
    unsigned = jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(unsigned)

    assert error.value.status_code == 403
    assert error.value.code == "BUSINESS_UNIT_CONTEXT_REQUIRED"


def test_oidc_rejects_wrong_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(_token(private_key, aud="another-api"))

    assert error.value.status_code == 401
    assert error.value.code == "UNAUTHENTICATED"


def test_oidc_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )
    now = int(time.time())

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(_token(private_key, iat=now - 600, exp=now - 300))

    assert error.value.status_code == 401


def test_oidc_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(
            _token(private_key, iss="https://issuer.example.evil")
        )

    assert error.value.status_code == 401
    assert error.value.code == "UNAUTHENTICATED"


def test_oidc_rejects_unsigned_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticator, _, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )
    now = int(time.time())
    unsigned = jwt.encode(
        {
            "sub": "user-123",
            "iss": "https://issuer.example",
            "aud": "ticket-agent",
            "iat": now,
            "exp": now + 300,
            "business_units": ["bu_demo"],
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(unsigned)

    assert error.value.status_code == 401
    assert error.value.code == "UNAUTHENTICATED"


def test_oidc_rejects_unknown_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )
    token = jwt.encode(
        jwt.decode(
            _token(private_key),
            options={"verify_signature": False},
        ),
        private_key,
        algorithm="RS256",
        headers={"kid": "rotated-away"},
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(token)

    assert error.value.status_code == 401
    assert "signing key" in error.value.detail


def test_oidc_requires_expiration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authenticator, private_key, public_jwk = _auth_fixture()
    monkeypatch.setattr(
        authenticator,
        "_fetch_json",
        lambda url: {"keys": [public_jwk]},
    )
    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": "https://issuer.example",
            "aud": "ticket-agent",
            "iat": int(time.time()),
            "business_units": ["bu_demo"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    with pytest.raises(ApiProblem) as error:
        authenticator.authenticate(token)

    assert error.value.status_code == 401


def test_oidc_mode_ignores_dev_identity_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_auth_mode="oidc",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="ticket-agent",
    )
    monkeypatch.setattr(
        "ticket_agent.identity.dependencies.get_settings",
        lambda: settings,
    )

    with pytest.raises(ApiProblem) as error:
        get_principal(
            authorization=None,
            x_actor_id="spoofed.admin",
            x_actor_role="admin",
            x_business_unit_id="bu_other",
        )

    assert error.value.status_code == 401
    assert error.value.code == "UNAUTHENTICATED"


def test_realm_roles_are_used_as_fallback() -> None:
    role = resolve_role(
        {"realm_access": {"roles": ["/ticket-supervisor"]}},
        "roles",
    )

    assert role == "supervisor"


@pytest.mark.parametrize(
    ("raw_role", "expected"),
    [
        ("knowledge_operator", "knowledge_operator"),
        ("business_manager", "business_manager"),
    ],
)
def test_platform_specific_roles_are_supported(
    raw_role: str,
    expected: str,
) -> None:
    assert resolve_role({"roles": [raw_role]}, "roles") == expected

