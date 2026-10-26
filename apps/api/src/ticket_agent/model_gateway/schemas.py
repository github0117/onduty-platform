from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ModelPurposeMetric(BaseModel):
    purpose: str
    calls: int
    total_tokens: int
    estimated_cost: float


class ModelMetricsResponse(BaseModel):
    calls: int
    succeeded: int
    failed: int
    denied: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    budget_exceeded: int = 0
    budget_forecast_alerts: int = 0
    by_purpose: list[ModelPurposeMetric] = Field(default_factory=list)


class ModelBudgetPeriodResponse(BaseModel):
    period: str
    starts_at: datetime
    ends_at: datetime
    elapsed_fraction: float
    usage: dict[str, float]
    limits: dict[str, float]
    utilization: dict[str, float]
    projected: dict[str, float]
    alerts: list[str]


class ModelBudgetResponse(BaseModel):
    employee_id: UUID
    business_unit_id: str
    exceeded: bool
    forecast_alert: bool
    periods: list[ModelBudgetPeriodResponse]


class RuntimeConfigResponse(BaseModel):
    app_env: str
    task_mode: str
    object_storage_provider: str
    model_provider: str
    model_name: str
    model_base_url_configured: bool
    model_api_key_configured: bool
    model_fallback_to_local: bool
    embedding_provider: str
    embedding_model_name: str
    embedding_base_url_configured: bool
    embedding_api_key_configured: bool
    embedding_dimensions: int
    claim_verifier_provider: str
    claim_verifier_model_name: str
    claim_verifier_enforce: bool
    rerank_provider: str
    rerank_model_name: str
    rerank_fallback_to_local: bool
    ticket_integration_provider: str
    ticket_api_url_configured: bool
    ticket_api_key_configured: bool
    customer_service_auto_reply_enabled: bool
    customer_service_auto_reply_min_confidence: float
    customer_service_auto_reply_max_characters: int
    ecommerce_channel_provider: str
    ecommerce_channel_url_configured: bool
    ecommerce_channel_api_key_configured: bool
    logistics_query_provider: str
    logistics_query_url_configured: bool
    logistics_query_api_key_configured: bool
    pinduoduo_channel_configured: bool
    pinduoduo_merchant_authorized: bool
    ecommerce_content_provider: str
    ecommerce_content_model_name: str
    ecommerce_content_base_url_configured: bool
    ecommerce_content_api_key_configured: bool
    ecommerce_content_fallback_to_local: bool
    ecommerce_image_provider: str
    ecommerce_image_model_name: str
    ecommerce_image_base_url_configured: bool
    ecommerce_image_api_key_configured: bool
    ecommerce_visual_audit_provider: str
    ecommerce_visual_audit_model_name: str
    ecommerce_visual_audit_api_key_configured: bool
    ecommerce_tts_provider: str
    ecommerce_tts_model_name: str
    ecommerce_tts_voice: str
    ecommerce_tts_api_key_configured: bool

