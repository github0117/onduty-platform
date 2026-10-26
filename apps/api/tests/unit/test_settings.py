import pytest
from pydantic import ValidationError

from ticket_agent.shared.settings import Settings


def test_external_model_inherits_content_credentials() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="",
        model_api_key="",
        model_name="",
        ecommerce_content_provider="openai_compatible",
        ecommerce_content_base_url="https://model.example/v1",
        ecommerce_content_api_key="test-only-key",
        ecommerce_content_model_name="chat-model",
    )

    assert settings.model_base_url == "https://model.example/v1"
    assert settings.model_api_key == "test-only-key"
    assert settings.model_name == "chat-model"


def test_external_model_preserves_explicit_model_credentials() -> None:
    settings = Settings(
        model_provider="openai_compatible",
        model_base_url="https://primary.example/v1",
        model_api_key="primary-key",
        model_name="primary-model",
        ecommerce_content_provider="openai_compatible",
        ecommerce_content_base_url="https://content.example/v1",
        ecommerce_content_api_key="content-key",
        ecommerce_content_model_name="content-model",
    )

    assert settings.model_base_url == "https://primary.example/v1"
    assert settings.model_api_key == "primary-key"
    assert settings.model_name == "primary-model"


def test_production_rejects_dev_authentication() -> None:
    with pytest.raises(ValidationError, match="APP_AUTH_MODE=dev"):
        Settings(app_env="production", app_auth_mode="dev")


def test_development_allows_dev_authentication() -> None:
    settings = Settings(app_env="development", app_auth_mode="dev")

    assert settings.app_auth_mode == "dev"


def test_production_requires_complete_oidc_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC_ISSUER_URL"):
        Settings(
            app_env="production",
            app_auth_mode="oidc",
            oidc_issuer_url="https://issuer.example",
        )


def test_production_accepts_configured_oidc() -> None:
    settings = Settings(
        app_env="production",
        app_auth_mode="oidc",
        oidc_issuer_url="https://issuer.example",
        oidc_audience="ticket-agent",
    )

    assert settings.app_auth_mode == "oidc"


def test_claim_verifier_defaults_to_local() -> None:
    assert (
        Settings.model_fields["claim_verifier_provider"].default == "local"
    )
