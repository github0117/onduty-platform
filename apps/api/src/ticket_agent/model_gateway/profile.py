from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ticket_agent.classification.classifier import MockClassifier
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.claim_verifier import (
    ClaimVerifier,
    ExternalClaimVerifier,
    HeuristicClaimVerifier,
    get_claim_verifier,
)
from ticket_agent.knowledge.rerank import ExternalHTTPReranker, Reranker, get_reranker
from ticket_agent.knowledge.retrieval import HybridReranker
from ticket_agent.model_gateway.local import LocalModelGateway
from ticket_agent.model_gateway.openai_compatible import OpenAICompatibleGateway
from ticket_agent.model_gateway.types import TicketModelGateway
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.settings import Settings, get_settings
from ticket_agent.tickets.drafts import DraftService

Provider = Literal["local", "openai_compatible"]


class ModelEndpointProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Provider | None = None
    model_name: str | None = Field(default=None, max_length=160)
    fallback_to_local: bool | None = None
    confidence_threshold: float | None = Field(default=None, ge=0, le=1)


class ClaimVerifierProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Literal["inherit", "none", "local", "external"] = "inherit"
    model_name: str | None = Field(default=None, max_length=160)
    enforce: bool | None = None
    fallback_to_local: bool | None = None


class RerankProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Literal["inherit", "local", "external"] = "inherit"
    model_name: str | None = Field(default=None, max_length=160)
    vector_weight: float | None = Field(default=None, ge=0, le=1)
    lexical_weight: float | None = Field(default=None, ge=0, le=1)
    enabled: bool = True
    fallback_to_local: bool | None = None


class BudgetProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    daily_calls: int | None = Field(default=None, ge=0)
    daily_tokens: int | None = Field(default=None, ge=0)
    daily_cost: float | None = Field(default=None, ge=0)
    weekly_calls: int | None = Field(default=None, ge=0)
    weekly_tokens: int | None = Field(default=None, ge=0)
    weekly_cost: float | None = Field(default=None, ge=0)
    monthly_calls: int | None = Field(default=None, ge=0)
    monthly_tokens: int | None = Field(default=None, ge=0)
    monthly_cost: float | None = Field(default=None, ge=0)


class EmployeeModelProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    classification: ModelEndpointProfile = Field(default_factory=ModelEndpointProfile)
    generation: ModelEndpointProfile = Field(default_factory=ModelEndpointProfile)
    claim_verifier: ClaimVerifierProfile = Field(default_factory=ClaimVerifierProfile)
    rerank: RerankProfile = Field(default_factory=RerankProfile)
    budgets: BudgetProfile = Field(default_factory=BudgetProfile)


def resolve_model_profile(employee: DigitalEmployee) -> EmployeeModelProfile:
    return EmployeeModelProfile.model_validate(employee.model_profile_json)


def build_classifier_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> MockClassifier:
    profile = resolve_model_profile(employee).classification
    settings = _settings_for(profile)
    gateway = _build_gateway(settings, profile.provider, usage_guard)
    return MockClassifier(
        gateway=gateway,
        confidence_threshold=profile.confidence_threshold,
    )


def build_draft_service_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> DraftService:
    model_profile = resolve_model_profile(employee)
    profile = model_profile.generation
    settings = _settings_for(
        profile,
        allow_ecommerce_content_credentials=True,
    )
    verifier = _build_claim_verifier(
        model_profile.claim_verifier,
        usage_guard=usage_guard,
    )
    resolved_provider = profile.provider or settings.model_provider
    if resolved_provider == "openai_compatible":
        gateway: TicketModelGateway = OpenAICompatibleGateway(
            settings,
            claim_verifier=verifier,
            use_configured_claim_verifier=False,
            usage_guard=usage_guard,
            employee_instructions=_employee_instruction(employee),
        )
    else:
        gateway = LocalModelGateway()
    return DraftService(gateway=gateway)


def build_reply_optimizer_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> OpenAICompatibleGateway:
    profile = resolve_model_profile(employee).generation
    settings = _settings_for(
        profile,
        allow_ecommerce_content_credentials=True,
    )
    resolved_provider = profile.provider or settings.model_provider
    if resolved_provider != "openai_compatible":
        raise ValueError(
            "Reply optimization requires an openai_compatible generation model."
        )
    return OpenAICompatibleGateway(
        settings,
        use_configured_claim_verifier=False,
        usage_guard=usage_guard,
        employee_instructions=_employee_instruction(employee),
    )


def build_tool_planner_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> OpenAICompatibleGateway | None:
    profile = resolve_model_profile(employee).generation
    settings = _settings_for(
        profile,
        allow_ecommerce_content_credentials=True,
    )
    if (profile.provider or settings.model_provider) != "openai_compatible":
        return None
    return OpenAICompatibleGateway(
        settings,
        use_configured_claim_verifier=False,
        usage_guard=usage_guard,
    )


def build_workforce_gateway_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> TicketModelGateway:
    profile = resolve_model_profile(employee).generation
    settings = _settings_for(
        profile,
        allow_ecommerce_content_credentials=True,
    )
    return _build_gateway(
        settings,
        profile.provider,
        usage_guard,
        employee_instructions=_employee_instruction(employee),
    )


def build_reranker_for_employee(
    employee: DigitalEmployee,
    *,
    usage_guard: ModelUsageGuard | None = None,
) -> Reranker:
    profile = resolve_model_profile(employee).rerank
    settings = get_settings()
    if profile.provider == "inherit":
        return get_reranker()
    vector_weight = (
        profile.vector_weight
        if profile.vector_weight is not None
        else settings.knowledge_vector_weight
    )
    lexical_weight = (
        profile.lexical_weight
        if profile.lexical_weight is not None
        else settings.knowledge_lexical_weight
    )
    if profile.provider == "external":
        updates: dict[str, object] = {
            "knowledge_rerank_provider": "external",
            "knowledge_vector_weight": vector_weight,
            "knowledge_lexical_weight": lexical_weight,
        }
        if profile.model_name is not None:
            updates["rerank_model_name"] = profile.model_name
        if profile.fallback_to_local is not None:
            updates["rerank_fallback_to_local"] = profile.fallback_to_local
        return ExternalHTTPReranker(
            settings.model_copy(update=updates),
            usage_guard=usage_guard,
        )
    return HybridReranker(
        vector_weight=vector_weight,
        lexical_weight=lexical_weight,
        enabled=profile.enabled,
    )


def _settings_for(
    profile: ModelEndpointProfile,
    *,
    allow_ecommerce_content_credentials: bool = False,
) -> Settings:
    settings = get_settings()
    updates: dict[str, object] = {}
    if profile.provider is not None:
        updates["model_provider"] = profile.provider
    if profile.model_name is not None:
        updates["model_name"] = profile.model_name
    if profile.fallback_to_local is not None:
        updates["model_fallback_to_local"] = profile.fallback_to_local
    if (
        allow_ecommerce_content_credentials
        and settings.ecommerce_content_provider == "openai_compatible"
    ):
        if (
            profile.provider is None
            and not settings.model_base_url
            and settings.ecommerce_content_base_url
        ):
            updates["model_provider"] = "openai_compatible"
        if not settings.model_base_url:
            updates["model_base_url"] = settings.ecommerce_content_base_url
        if not settings.model_api_key:
            updates["model_api_key"] = settings.ecommerce_content_api_key
        if profile.model_name is None and settings.ecommerce_content_model_name:
            updates["model_name"] = settings.ecommerce_content_model_name
        if (
            settings.model_timeout_seconds
            == Settings.model_fields["model_timeout_seconds"].default
        ):
            updates["model_timeout_seconds"] = (
                settings.ecommerce_content_timeout_seconds
            )
    return settings.model_copy(update=updates)


def _build_gateway(
    settings: Settings,
    provider: Provider | None,
    usage_guard: ModelUsageGuard | None,
    *,
    employee_instructions: str | None = None,
) -> TicketModelGateway:
    resolved_provider = provider or settings.model_provider
    if resolved_provider == "openai_compatible":
        return OpenAICompatibleGateway(
            settings,
            use_configured_claim_verifier=False,
            usage_guard=usage_guard,
            employee_instructions=employee_instructions,
        )
    return LocalModelGateway()


def _employee_instruction(employee: DigitalEmployee) -> str | None:
    text = (employee.instruction_text or "").strip()
    return text or None


def _build_claim_verifier(
    profile: ClaimVerifierProfile,
    *,
    usage_guard: ModelUsageGuard | None,
) -> ClaimVerifier | None:
    settings = get_settings()
    if profile.provider == "inherit":
        return get_claim_verifier()
    if profile.provider == "none":
        return None
    updates: dict[str, object] = {}
    if profile.model_name is not None:
        updates["claim_verifier_model_name"] = profile.model_name
    if profile.enforce is not None:
        updates["claim_verifier_enforce"] = profile.enforce
    if profile.fallback_to_local is not None:
        updates["claim_verifier_fallback_to_local"] = profile.fallback_to_local
    claim_settings = settings.model_copy(update=updates)
    if profile.provider == "external":
        return ExternalClaimVerifier(
            claim_settings,
            usage_guard=usage_guard,
        )
    return HeuristicClaimVerifier(enforce=claim_settings.claim_verifier_enforce)

