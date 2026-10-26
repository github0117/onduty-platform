from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TicketCategory = Literal[
    "ecommerce_presales",
    "ecommerce_aftersales",
    "access_identity",
    "product_howto",
    "service_incident",
    "billing_invoice",
    "transaction_dispute",
    "complaint_escalation",
    "data_privacy_security",
    "other_unclassified",
]


class ModelClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: TicketCategory
    secondary: str = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0, le=1)
    risk_tags: list[str] = Field(default_factory=list, max_length=10)
    summary: str = Field(min_length=1, max_length=400)


class DraftClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    claim_type: Literal["greeting", "instruction", "policy", "closing"]
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=10)


class GeneratedDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    claims: list[DraftClaim] = Field(min_length=1, max_length=30)
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=10)


class OptimizedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)


class AgentToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    input_schema: dict[str, object] = Field(default_factory=dict)
    is_write: bool = False


class ToolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str | None = Field(default=None, max_length=200)
    arguments: dict[str, object] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=500)


class ToolPlanWire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str | None = Field(default=None, max_length=200)
    arguments_json: str = "{}"
    reason: str = Field(default="", max_length=500)


class WorkforceStepModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    findings: list[str] = Field(default_factory=list, max_length=10)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    requires_human: bool = False
    cited_chunk_ids: list[str] = Field(default_factory=list, max_length=10)


@dataclass(frozen=True)
class GatewayResponse:
    classification: ModelClassification
    provider: str
    model: str
    fallback_used: bool = False


@dataclass(frozen=True)
class DraftSnippet:
    chunk_id: str
    title: str
    version: str
    content: str


@dataclass(frozen=True)
class DraftGenerationResponse:
    draft: GeneratedDraft
    provider: str
    model: str
    fallback_used: bool = False
    claim_verifications: list["ClaimVerification"] = field(default_factory=list)


@dataclass(frozen=True)
class WorkforceStepResponse:
    output: WorkforceStepModelOutput
    provider: str
    model: str
    fallback_used: bool = False


@dataclass(frozen=True)
class ClaimVerification:
    claim_index: int
    verdict: Literal["supported", "unsupported", "uncertain"]
    confidence: float
    reason: str
    provider: str
    model: str


class ModelGatewayError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        code: str = "MODEL_GATEWAY_ERROR",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class TicketModelGateway(Protocol):
    @property
    def name(self) -> str: ...

    def classify(
        self,
        *,
        subject: str,
        body: str,
    ) -> GatewayResponse: ...

    def generate_draft(
        self,
        *,
        subject: str,
        body: str,
        category: str,
        queue_id: str,
        snippets: list[DraftSnippet],
        skill_instructions: str | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> DraftGenerationResponse: ...

    def generate_workforce_step(
        self,
        *,
        task_title: str,
        objective: str,
        context: dict[str, object],
        step_title: str,
        instructions: str,
        snippets: list[DraftSnippet],
        skill_instructions: str | None = None,
    ) -> WorkforceStepResponse: ...

