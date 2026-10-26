from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceInput(BaseModel):
    system: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=32)
    external_ticket_id: str = Field(min_length=1, max_length=128)


class RequesterInput(BaseModel):
    external_ref: str = Field(min_length=1, max_length=128)
    customer_tier: str = Field(default="standard", max_length=32)


class AttachmentInput(BaseModel):
    external_ref: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(ge=0)


class TicketCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    employee_id: UUID | None = None
    source: SourceInput
    requester: RequesterInput
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=100_000)
    locale: str = Field(default="zh-CN", max_length=20)
    attachments: list[AttachmentInput] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("subject", "body")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class TicketAccepted(BaseModel):
    id: UUID
    employee_id: UUID | None
    status: str
    workflow_state: str
    version: int
    created_at: datetime


class ClassificationView(BaseModel):
    primary: str
    secondary: str
    confidence: float


class PriorityView(BaseModel):
    level: str
    reason_codes: list[str]


class RiskView(BaseModel):
    level: str
    tags: list[str]
    reason_codes: list[str]


class RoutingView(BaseModel):
    queue_id: str | None
    needs_human: bool
    human_reason: str | None


class CitationView(BaseModel):
    chunk_id: str | None = None
    document_id: str
    space_id: str | None = None
    title: str
    version: str


class ClaimView(BaseModel):
    text: str
    claim_type: str
    cited_chunk_ids: list[str] = Field(default_factory=list)
    verification_verdict: str = "not_checked"
    verification_confidence: float | None = None
    verification_reason: str | None = None
    verification_provider: str | None = None


class DraftView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    status: str
    generator_provider: str | None
    generator_model: str | None
    grounding_status: str
    citations: list[CitationView] = Field(default_factory=list)
    claims: list[ClaimView] = Field(default_factory=list)
    created_at: datetime
    reviewed_at: datetime | None


class SyncView(BaseModel):
    status: str
    attempts: int
    error: str | None
    external_request_id: str | None
    synced_at: datetime | None


class DigitalEmployeeReference(BaseModel):
    id: UUID
    employee_key: str
    name: str
    version: str
    workflow_key: str


class TicketDetail(BaseModel):
    id: UUID
    business_unit_id: str
    employee: DigitalEmployeeReference
    source: SourceInput
    requester: RequesterInput
    subject: str
    body: str
    summary: str | None
    status: str
    workflow_state: str
    classification: ClassificationView | None
    priority: PriorityView | None
    risk: RiskView | None
    routing: RoutingView
    needs_human: bool
    draft: DraftView | None
    sync: SyncView
    version: int
    created_at: datetime
    updated_at: datetime
    allowed_actions: list[str]


class TicketListItem(BaseModel):
    id: UUID
    subject: str
    status: str
    workflow_state: str
    category_primary: str | None
    priority: str | None
    risk_level: str | None
    queue_id: str | None
    needs_human: bool
    version: int
    created_at: datetime
    updated_at: datetime


class TicketList(BaseModel):
    items: list[TicketListItem]
    total: int


class TakeoverRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason_code: str = Field(default="AGENT_REQUESTED", max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class ReviewRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: str
    edited_text: str | None = Field(default=None, max_length=10_000)
    reason_code: str = Field(default="AGENT_APPROVED", max_length=64)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        allowed = {"ACCEPTED", "EDITED_AND_ACCEPTED", "REJECTED", "ESCALATED"}
        if value not in allowed:
            raise ValueError(f"decision must be one of {sorted(allowed)}")
        return value


class ClassificationOverrideRequest(BaseModel):
    expected_version: int = Field(ge=1)
    primary: str = Field(min_length=1, max_length=64)
    secondary: str = Field(min_length=1, max_length=64)
    reason_code: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class SyncRetryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason_code: str = Field(default="MANUAL_SYNC_RETRY", max_length=64)


class SyncBatchRetryRequest(BaseModel):
    ticket_ids: list[UUID] = Field(min_length=1, max_length=100)
    reason_code: str = Field(default="BATCH_SYNC_RETRY", max_length=64)


class SyncBatchItem(BaseModel):
    ticket_id: UUID
    accepted: bool
    code: str
    version: int | None = None
    workflow_state: str | None = None
    sync_status: str | None = None


class SyncBatchRetryResponse(BaseModel):
    items: list[SyncBatchItem]


class MutationResult(BaseModel):
    ticket_id: UUID
    version: int
    status: str
    workflow_state: str
    message: str


class HealthResponse(BaseModel):
    status: str
    database: str
    environment: str

