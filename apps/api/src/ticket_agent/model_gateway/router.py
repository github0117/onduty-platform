from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from ticket_agent.api.dependencies import Actor, DbSession
from ticket_agent.digital_employees.service import DigitalEmployeeService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_metrics_viewer,
    resolve_business_unit,
)
from ticket_agent.model_gateway.schemas import (
    ModelBudgetResponse,
    ModelMetricsResponse,
    RuntimeConfigResponse,
)
from ticket_agent.model_gateway.usage import ModelUsageService
from ticket_agent.shared.settings import get_settings

router = APIRouter()


@router.get("/system/runtime", response_model=RuntimeConfigResponse)
def get_runtime_config(principal: Actor) -> RuntimeConfigResponse:
    ensure_metrics_viewer(principal)
    settings = get_settings()
    return RuntimeConfigResponse(
        app_env=settings.app_env,
        task_mode=settings.task_mode,
        object_storage_provider=settings.object_storage_provider,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
        model_base_url_configured=bool(settings.model_base_url),
        model_api_key_configured=bool(settings.model_api_key),
        model_fallback_to_local=settings.model_fallback_to_local,
        embedding_provider=settings.embedding_provider,
        embedding_model_name=settings.embedding_model_name,
        embedding_base_url_configured=bool(
            settings.embedding_base_url or settings.model_base_url
        ),
        embedding_api_key_configured=bool(
            settings.embedding_api_key or settings.model_api_key
        ),
        embedding_dimensions=settings.embedding_dimensions,
        claim_verifier_provider=settings.claim_verifier_provider,
        claim_verifier_model_name=settings.claim_verifier_model_name,
        claim_verifier_enforce=settings.claim_verifier_enforce,
        rerank_provider=settings.knowledge_rerank_provider,
        rerank_model_name=settings.rerank_model_name,
        rerank_fallback_to_local=settings.rerank_fallback_to_local,
        ticket_integration_provider=settings.ticket_integration_provider,
        ticket_api_url_configured=bool(settings.ticket_api_base_url),
        ticket_api_key_configured=bool(settings.ticket_api_key),
        customer_service_auto_reply_enabled=(
            settings.customer_service_auto_reply_enabled
        ),
        customer_service_auto_reply_min_confidence=(
            settings.customer_service_auto_reply_min_confidence
        ),
        customer_service_auto_reply_max_characters=(
            settings.customer_service_auto_reply_max_characters
        ),
        ecommerce_channel_provider=settings.ecommerce_channel_provider,
        ecommerce_channel_url_configured=bool(settings.ecommerce_channel_base_url),
        ecommerce_channel_api_key_configured=bool(
            settings.ecommerce_channel_api_key
        ),
        logistics_query_provider=settings.logistics_query_provider,
        logistics_query_url_configured=bool(
            settings.logistics_query_base_url
        ),
        logistics_query_api_key_configured=bool(
            settings.logistics_query_api_key
        ),
        pinduoduo_channel_configured=bool(
            settings.pinduoduo_client_id
            and settings.pinduoduo_client_secret
        ),
        pinduoduo_merchant_authorized=bool(
            settings.pinduoduo_access_token
        ),
        ecommerce_content_provider=settings.ecommerce_content_provider,
        ecommerce_content_model_name=settings.ecommerce_content_model_name,
        ecommerce_content_base_url_configured=bool(
            settings.ecommerce_content_base_url or settings.model_base_url
        ),
        ecommerce_content_api_key_configured=bool(
            settings.ecommerce_content_api_key or settings.model_api_key
        ),
        ecommerce_content_fallback_to_local=(
            settings.ecommerce_content_fallback_to_local
        ),
        ecommerce_image_provider=settings.ecommerce_image_provider,
        ecommerce_image_model_name=settings.ecommerce_image_model_name,
        ecommerce_image_base_url_configured=bool(
            settings.ecommerce_image_base_url or settings.model_base_url
        ),
        ecommerce_image_api_key_configured=bool(
            settings.ecommerce_image_api_key
            or settings.ecommerce_content_api_key
            or settings.model_api_key
        ),
        ecommerce_visual_audit_provider=(
            settings.ecommerce_visual_audit_provider
        ),
        ecommerce_visual_audit_model_name=(
            settings.ecommerce_visual_audit_model_name
        ),
        ecommerce_visual_audit_api_key_configured=bool(
            settings.ecommerce_content_api_key or settings.model_api_key
        ),
        ecommerce_tts_provider=settings.ecommerce_tts_provider,
        ecommerce_tts_model_name=settings.ecommerce_tts_model_name,
        ecommerce_tts_voice=settings.ecommerce_tts_voice,
        ecommerce_tts_api_key_configured=bool(
            settings.ecommerce_content_api_key or settings.model_api_key
        ),
    )


@router.get("/metrics/models/budget", response_model=ModelBudgetResponse)
def get_model_budget(
    db: DbSession,
    principal: Actor,
    employee_id: Annotated[UUID, Query()],
) -> ModelBudgetResponse:
    ensure_metrics_viewer(principal)
    employee = DigitalEmployeeService(db).get(employee_id)
    ensure_business_unit_access(principal, employee.business_unit_id)
    payload = ModelUsageService(db).budget_status(employee)
    return ModelBudgetResponse.model_validate(payload)


@router.get("/metrics/models", response_model=ModelMetricsResponse)
def get_model_metrics(
    db: DbSession,
    principal: Actor,
    employee_id: Annotated[UUID | None, Query()] = None,
    business_unit_id: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
) -> ModelMetricsResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    if employee_id is not None:
        employee = DigitalEmployeeService(db).get(employee_id)
        ensure_business_unit_access(principal, employee.business_unit_id)
    payload = ModelUsageService(db).summary(
        employee_id=employee_id,
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    return ModelMetricsResponse.model_validate(payload)

