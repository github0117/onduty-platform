from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class KnowledgeSpaceCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    code: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    domain: str = Field(default="general", min_length=1, max_length=64)
    channel: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=128)
    category_profile_id: UUID | None = None
    workflow_key: str | None = Field(default=None, max_length=100)
    owner_id: str = Field(min_length=1, max_length=128)
    evaluation_required: bool = False


class KnowledgeSpaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    domain: str | None = Field(default=None, min_length=1, max_length=64)
    channel: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=128)
    category_profile_id: UUID | None = None
    workflow_key: str | None = Field(default=None, max_length=100)
    owner_id: str | None = Field(default=None, min_length=1, max_length=128)
    evaluation_required: bool | None = None
    status: Literal["ACTIVE", "DISABLED"] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeSpaceUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class KnowledgeSpaceView(BaseModel):
    id: UUID
    business_unit_id: str
    code: str
    name: str
    description: str
    domain: str
    channel: str | None
    category: str | None
    category_profile_id: UUID | None
    workflow_key: str | None
    owner_id: str
    evaluation_required: bool
    status: str
    document_count: int
    created_at: datetime
    updated_at: datetime


class EmployeeKnowledgeBindingInput(BaseModel):
    knowledge_space_id: UUID
    workflow_key: str | None = Field(default=None, max_length=100)
    scope: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class EmployeeKnowledgeBindingReplace(BaseModel):
    bindings: list[EmployeeKnowledgeBindingInput] = Field(max_length=50)


class EmployeeKnowledgeBindingView(BaseModel):
    id: UUID
    employee_id: UUID
    knowledge_space_id: UUID
    workflow_key: str | None
    scope: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentCreate(BaseModel):
    space_id: UUID | None = None
    business_unit_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    doc_type: Literal["SOP", "FAQ", "POLICY", "PRODUCT"]
    owner_id: str = Field(min_length=1, max_length=128)
    scope: dict[str, Any] = Field(default_factory=dict)


class KnowledgeDocumentUpdate(BaseModel):
    space_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    doc_type: Literal["SOP", "FAQ", "POLICY", "PRODUCT"] | None = None
    owner_id: str | None = Field(default=None, min_length=1, max_length=128)
    scope: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeDocumentUpdate":
        if all(
            value is None
            for value in (
                self.space_id,
                self.title,
                self.doc_type,
                self.owner_id,
                self.scope,
            )
        ):
            raise ValueError("at least one field must be provided")
        return self


class KnowledgeVersionCreate(BaseModel):
    version_label: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=10, max_length=500_000)
    effective_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    effective_to: datetime | None = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class KnowledgePublishRequest(BaseModel):
    release_note: str = Field(default="", max_length=1000)


class KnowledgeDocumentView(BaseModel):
    id: UUID
    space_id: UUID | None
    business_unit_id: str
    title: str
    doc_type: str
    owner_id: str
    scope: dict[str, Any]
    source_type: str | None
    source_ref: str | None
    source_version: str | None
    sync_status: str | None
    last_synced_at: datetime | None
    status: str
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class KnowledgeVersionView(BaseModel):
    id: UUID
    document_id: UUID
    version_label: str
    status: str
    content_hash: str
    effective_from: datetime
    effective_to: datetime | None
    embedding_model: str
    source_filename: str | None
    source_mime_type: str | None
    source_size_bytes: int | None
    source_object_key: str | None
    parser_name: str | None
    parser_version: str | None
    ingestion_error: str | None
    processing_started_at: datetime | None
    processed_at: datetime | None
    chunk_count: int
    published_at: datetime | None
    created_at: datetime


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    business_unit_id: str = Field(min_length=1, max_length=64)
    space_id: UUID | None = None
    employee_id: UUID | None = None
    scope: dict[str, str] = Field(default_factory=dict)
    top_k: int | None = Field(default=None, ge=1, le=20)


class KnowledgeHitView(BaseModel):
    chunk_id: UUID
    document_id: UUID
    space_id: UUID | None
    title: str
    version: str
    content: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    items: list[KnowledgeHitView]
    embedding_model: str
    reranker: str
    retrieval_mode: Literal["dense", "hybrid"] = "dense"


class KnowledgeUploadAccepted(BaseModel):
    version_id: UUID
    document_id: UUID
    version_label: str
    status: str
    source_object_key: str


class ProductKnowledgeSyncRequest(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    product_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ProductKnowledgeSyncItem(BaseModel):
    product_id: UUID
    sku: str
    document_id: UUID | None = None
    version_id: UUID | None = None
    status: str
    changed: bool
    error_message: str | None = None


class ProductKnowledgeSyncResult(BaseModel):
    business_unit_id: str
    requested: int
    synced: int
    unchanged: int
    failed: int
    items: list[ProductKnowledgeSyncItem]


KnowledgeEvaluationDataset = Literal["TUNING", "HOLDOUT"]


class KnowledgeEvaluationPassage(BaseModel):
    """A ground-truth text fragment inside one document.

    Storing the text instead of a chunk id keeps the case valid across
    reindexes and chunking changes; the chunk is resolved at run time.
    """

    document_id: UUID
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def require_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("passage text must not be blank")
        return cleaned


class KnowledgeEvaluationCaseCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    knowledge_space_id: UUID | None = None
    employee_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=20_000)
    dataset: KnowledgeEvaluationDataset = "TUNING"
    expected_titles: list[str] = Field(default_factory=list, max_length=20)
    expected_chunk_ids: list[UUID] = Field(default_factory=list, max_length=50)
    expected_passages: list[KnowledgeEvaluationPassage] = Field(
        default_factory=list, max_length=20
    )
    expected_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    negative_document_ids: list[UUID] = Field(default_factory=list, max_length=20)
    expect_no_grounding: bool = False
    scope: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", "query")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name and query must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_expectations(self) -> "KnowledgeEvaluationCaseCreate":
        if set(self.expected_document_ids) & set(self.negative_document_ids):
            raise ValueError(
                "negative_document_ids must not overlap expected_document_ids"
            )
        if self.expect_no_grounding and (
            self.expected_titles
            or self.expected_chunk_ids
            or self.expected_passages
            or self.expected_document_ids
        ):
            raise ValueError(
                "expect_no_grounding cannot be combined with expected matches"
            )
        return self


class KnowledgeEvaluationCaseView(BaseModel):
    id: UUID
    business_unit_id: str
    knowledge_space_id: UUID | None
    employee_id: UUID | None
    name: str
    query: str
    dataset: KnowledgeEvaluationDataset
    expected_titles: list[str]
    expected_chunk_ids: list[UUID]
    expected_passages: list[KnowledgeEvaluationPassage]
    expected_document_ids: list[UUID]
    negative_document_ids: list[UUID]
    expect_no_grounding: bool
    scope: dict[str, str]
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class KnowledgeEvaluationCaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    query: str | None = Field(default=None, min_length=1, max_length=20_000)
    dataset: KnowledgeEvaluationDataset | None = None
    expected_titles: list[str] | None = Field(default=None, max_length=20)
    expected_chunk_ids: list[UUID] | None = Field(default=None, max_length=50)
    expected_passages: list[KnowledgeEvaluationPassage] | None = Field(
        default=None, max_length=20
    )
    expected_document_ids: list[UUID] | None = Field(default=None, max_length=20)
    negative_document_ids: list[UUID] | None = Field(default=None, max_length=20)
    expect_no_grounding: bool | None = None
    scope: dict[str, str] | None = None
    enabled: bool | None = None

    @field_validator("name", "query")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name and query must not be blank")
        return cleaned

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeEvaluationCaseUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class KnowledgeEvaluationRunCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    knowledge_space_id: UUID | None = None
    dataset: KnowledgeEvaluationDataset = "TUNING"
    top_k: int = Field(default=5, ge=1, le=20)
    min_recall_at_k: float = Field(default=0.8, ge=0, le=1)
    min_mrr: float = Field(default=0.6, ge=0, le=1)
    min_no_grounding_accuracy: float = Field(default=0.8, ge=0, le=1)


class KnowledgeEvaluationRunView(BaseModel):
    id: UUID
    business_unit_id: str
    dataset: KnowledgeEvaluationDataset
    status: str
    verdict: str
    top_k: int
    case_count: int
    passed_cases: int
    failed_cases: int
    recall_at_k: float | None
    mrr: float | None
    no_grounding_accuracy: float | None
    chunk_recall_at_k: float | None
    chunk_mrr: float | None
    document_recall_at_k: float | None
    document_mrr: float | None
    context_precision: float | None
    negative_violation_rate: float | None
    avg_context_chars: float | None = None
    avg_context_tokens: float | None = None
    thresholds: dict[str, Any]
    baseline: dict[str, Any]
    results: list[dict[str, Any]]
    error_message: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class KnowledgeEvaluationRunList(BaseModel):
    items: list[KnowledgeEvaluationRunView]
    total: int


class KnowledgeRepairTaskView(BaseModel):
    id: UUID
    business_unit_id: str
    knowledge_space_id: UUID | None
    evaluation_run_id: UUID | None
    evaluation_case_id: UUID | None
    status: str
    priority: str
    title: str
    query: str
    expected_titles: list[str]
    returned_titles: list[str]
    assignee_id: str | None
    resolution_note: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    occurrence_count: int = 1


class KnowledgeRepairTaskUpdate(BaseModel):
    status: Literal["OPEN", "IN_REPAIR", "VERIFIED", "CLOSED"] | None = None
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    assignee_id: str | None = Field(default=None, max_length=128)
    resolution_note: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_change(self) -> "KnowledgeRepairTaskUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("at least one field must be provided")
        return self


class KnowledgeRepairTaskList(BaseModel):
    items: list[KnowledgeRepairTaskView]
    total: int


class KnowledgeFeedbackCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    knowledge_space_id: UUID | None = None
    employee_id: UUID | None = None
    ticket_id: UUID | None = None
    query: str = Field(min_length=1, max_length=20_000)
    answer: str = Field(default="", max_length=50_000)
    rating: Literal["POSITIVE", "NEGATIVE"]
    reason_code: str = Field(default="USER_FEEDBACK", max_length=64)
    details: str | None = Field(default=None, max_length=5000)


class KnowledgeFeedbackView(BaseModel):
    id: UUID
    business_unit_id: str
    knowledge_space_id: UUID | None
    employee_id: UUID | None
    ticket_id: UUID | None
    query: str
    answer: str
    rating: str
    reason_code: str
    details: str | None
    repair_task_id: UUID | None
    created_by: str
    created_at: datetime


class KnowledgeFeedbackList(BaseModel):
    items: list[KnowledgeFeedbackView]
    total: int


class KnowledgeFeedbackClusterView(BaseModel):
    knowledge_space_id: UUID | None
    reason_code: str
    count: int
    repair_task_ids: list[UUID]
    latest_query: str


class KnowledgeFeedbackClusterList(BaseModel):
    items: list[KnowledgeFeedbackClusterView]
    total: int


class RagMetricsResponse(BaseModel):
    draft_count: int
    grounded_count: int
    no_knowledge_count: int
    citation_total: int
    average_citations: float
    grounding_rate: float
    claim_count: int
    cited_claim_count: int
    policy_claim_count: int
    policy_citation_coverage: float
    semantic_verified_claim_count: int
    semantic_unsupported_claim_count: int
    provider_counts: dict[str, int]
    embedding_model: str
    # "demo" means the local feature-hash embedding: retrieval works but is not
    # semantic, so the UI must not present it as production quality.
    embedding_quality: Literal["demo", "semantic"]
    reindex_pending_versions: int
    stale_evaluation_chunk_refs: int


class KnowledgeReindexRequest(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    document_id: UUID | None = None
    chunking_version: str | None = Field(default=None, pattern="^v[12]$")


class KnowledgeReindexJobView(BaseModel):
    id: UUID
    business_unit_id: str
    document_id: UUID | None
    target_embedding_model: str
    target_chunking_version: str
    status: str
    total_versions: int
    processed_versions: int
    skipped_versions: int
    failed_versions: int
    attempt_count: int
    last_error: str | None
    requested_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class KnowledgeReindexJobList(BaseModel):
    items: list[KnowledgeReindexJobView]

