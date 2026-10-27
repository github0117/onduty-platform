from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "UniEmployee Ecommerce API"
    app_env: str = "development"
    app_auth_mode: str = "dev"
    oidc_issuer_url: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_roles_claim: str = "roles"
    oidc_customer_ref_claim: str = ""
    oidc_business_units_claim: str = "business_units"
    oidc_jwks_cache_seconds: int = 300
    oidc_http_timeout_seconds: float = 5.0
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/ticket_agent.db"
    database_pool_size: int = 20
    database_max_overflow: int = 20
    database_pool_timeout_seconds: float = 30.0
    max_request_bytes: int = 32 * 1024 * 1024
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = False
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_window_seconds: int = 60
    rate_limit_requests_per_minute: int = 120
    rate_limit_key_prefix: str = "ticket-agent:rate-limit"
    task_mode: Literal["inline", "celery"] = "inline"
    demo_reset_enabled: bool = True
    demo_reset_base_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] = ["http://localhost:5173"]
    classification_confidence_threshold: float = 0.80
    customer_service_auto_reply_enabled: bool = True
    customer_service_auto_reply_min_confidence: float = 0.85
    customer_service_auto_reply_max_characters: int = 1200
    mcp_refund_supervisor_limit: float = 500.0
    mcp_refund_absolute_limit: float = 5000.0
    mcp_reconciliation_max_attempts: int = 3
    mcp_reconciliation_batch_size: int = 20
    outbox_batch_size: int = 50
    outbox_retry_base_seconds: int = 5
    model_provider: Literal["local", "openai_compatible"] = "local"
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = ""
    model_timeout_seconds: float = 20.0
    model_max_retries: int = 2
    model_max_output_tokens: int = 800
    model_fallback_to_local: bool = True
    model_data_redaction_enabled: bool = True
    model_input_cost_per_1k_tokens: float = 0.0
    model_output_cost_per_1k_tokens: float = 0.0
    embedding_provider: Literal["local", "openai_compatible"] = "local"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model_name: str = ""
    embedding_dimensions: int = 256
    embedding_timeout_seconds: float = 20.0
    embedding_fallback_to_local: bool = True
    knowledge_chunk_size: int = 800
    knowledge_chunk_overlap: int = 100
    knowledge_chunking_version: Literal["v1", "v2"] = "v1"
    knowledge_chunk_target_chars: int = 800
    knowledge_chunk_max_chars: int = 1200
    knowledge_retrieval_mode: Literal["dense", "hybrid"] = "dense"
    knowledge_rrf_k: int = 60
    knowledge_query_context_enabled: bool = True
    knowledge_query_context_history_turns: int = 3
    knowledge_query_rewrite_enabled: bool = False
    knowledge_query_rewrite_variants: int = 2
    knowledge_query_rewrite_trigger_score: float = 0.3
    knowledge_query_rewrite_timeout_seconds: float = 2.0
    query_rewrite_base_url: str = ""
    query_rewrite_api_key: str = ""
    query_rewrite_model_name: str = ""
    knowledge_search_top_k: int = 5
    knowledge_min_score: float = 0.15
    knowledge_max_file_bytes: int = 20 * 1024 * 1024
    knowledge_reranker: Literal["hybrid", "vector"] = "hybrid"
    knowledge_vector_weight: float = 0.6
    knowledge_lexical_weight: float = 0.4
    knowledge_candidate_multiplier: int = 5
    knowledge_rerank_provider: Literal["local", "external"] = "local"
    knowledge_rerank_min_candidates: int = 1
    knowledge_rerank_trigger_score: float = 0.0
    knowledge_rerank_max_candidates: int = 30
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model_name: str = ""
    rerank_timeout_seconds: float = 3.0
    rerank_fallback_to_local: bool = True
    claim_verifier_provider: Literal["none", "local", "external"] = "local"
    claim_verifier_base_url: str = ""
    claim_verifier_api_key: str = ""
    claim_verifier_model_name: str = ""
    claim_verifier_timeout_seconds: float = 20.0
    claim_verifier_enforce: bool = False
    claim_verifier_fallback_to_local: bool = True
    ticket_integration_provider: Literal["local", "http_json"] = "local"
    ticket_api_base_url: str = ""
    ticket_api_key: str = ""
    ticket_api_timeout_seconds: float = 20.0
    ticket_sync_max_attempts: int = 5
    ecommerce_channel_provider: Literal["local", "http_json"] = "local"
    ecommerce_channel_base_url: str = ""
    ecommerce_channel_api_key: str = ""
    ecommerce_channel_timeout_seconds: float = 20.0
    logistics_query_provider: Literal["none", "http_json"] = "none"
    logistics_query_base_url: str = ""
    logistics_query_api_key: str = ""
    logistics_query_timeout_seconds: float = 20.0
    business_sandbox_provider: Literal["none", "http_json"] = "none"
    business_sandbox_base_url: str = ""
    business_sandbox_timeout_seconds: float = 5.0
    pinduoduo_api_base_url: str = "https://gw-api.pinduoduo.com/api/router"
    pinduoduo_client_id: str = ""
    pinduoduo_client_secret: str = ""
    pinduoduo_access_token: str = ""
    pinduoduo_api_timeout_seconds: float = 20.0
    ecommerce_content_provider: Literal["local", "openai_compatible"] = "local"
    ecommerce_content_base_url: str = ""
    ecommerce_content_api_key: str = ""
    ecommerce_content_model_name: str = ""
    ecommerce_content_timeout_seconds: float = 60.0
    ecommerce_content_fallback_to_local: bool = True
    ecommerce_image_provider: Literal[
        "local",
        "openai_compatible",
        "dashscope",
    ] = "local"
    ecommerce_image_base_url: str = ""
    ecommerce_image_api_key: str = ""
    ecommerce_image_model_name: str = ""
    ecommerce_image_timeout_seconds: float = 60.0
    ecommerce_image_fallback_to_local: bool = True
    ecommerce_image_cost_per_image: float = 0.0
    ecommerce_visual_audit_provider: Literal["none", "dashscope_ocr"] = "none"
    ecommerce_visual_audit_model_name: str = ""
    ecommerce_visual_audit_timeout_seconds: float = 60.0
    ecommerce_tts_provider: Literal["none", "dashscope_qwen"] = "none"
    ecommerce_tts_model_name: str = ""
    ecommerce_tts_voice: str = "Cherry"
    ecommerce_tts_timeout_seconds: float = 90.0
    ecommerce_subtitle_burn_in: bool = False
    ecommerce_subtitle_font_path: str = (
        "/app/assets/fonts/NotoSansCJKsc-Regular.otf"
    )
    ecommerce_ffmpeg_path: str = "ffmpeg"
    sync_alert_failure_rate: float = 0.1
    sync_alert_retrying_count: int = 20
    metrics_scrape_token: str = ""
    object_storage_provider: Literal["local", "s3"] = "local"
    object_storage_local_root: str = "./data/objects"
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key: str = "ticket_agent"
    s3_secret_key: str = "ticket_agent_local_only"
    s3_bucket: str = "ticket-agent"
    s3_region: str = "us-east-1"

    @field_validator("app_auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        if value not in {"dev", "oidc"}:
            raise ValueError("APP_AUTH_MODE must be 'dev' or 'oidc'")
        return value

    @model_validator(mode="after")
    def inherit_model_credentials(self) -> "Settings":
        if (
            self.model_provider == "openai_compatible"
            and self.ecommerce_content_provider == "openai_compatible"
        ):
            if not self.model_base_url:
                self.model_base_url = self.ecommerce_content_base_url
            if not self.model_api_key:
                self.model_api_key = self.ecommerce_content_api_key
            if not self.model_name and self.ecommerce_content_model_name:
                self.model_name = self.ecommerce_content_model_name
        return self

    @model_validator(mode="after")
    def inherit_query_rewrite_credentials(self) -> "Settings":
        # Query rewriting is an LLM call; reuse the configured model endpoint
        # when no dedicated rewrite endpoint is set. Keys are never defaulted
        # to a literal, only inherited from the runtime environment.
        if self.model_provider == "openai_compatible":
            if not self.query_rewrite_base_url:
                self.query_rewrite_base_url = self.model_base_url
            if not self.query_rewrite_api_key:
                self.query_rewrite_api_key = self.model_api_key
            if not self.query_rewrite_model_name:
                self.query_rewrite_model_name = self.model_name
        return self

    @model_validator(mode="after")
    def validate_production_auth(self) -> "Settings":
        if self.app_env in {"development", "test"}:
            return self
        if self.app_auth_mode == "dev":
            raise ValueError(
                "APP_AUTH_MODE=dev is only allowed when APP_ENV is "
                "development or test"
            )
        if self.app_auth_mode == "oidc" and (
            not self.oidc_issuer_url or not self.oidc_audience
        ):
            raise ValueError(
                "OIDC_ISSUER_URL and OIDC_AUDIENCE are required outside "
                "development"
            )
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env in {"development", "test"}

    def ensure_sqlite_directory(self) -> None:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return
        database_path = Path(self.database_url.removeprefix(prefix))
        database_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

