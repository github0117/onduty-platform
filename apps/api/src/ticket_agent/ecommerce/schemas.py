from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EcommerceProductCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=120)
    price: float = Field(ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EcommerceCategoryProfileCreate(BaseModel):
    business_unit_id: str = Field(min_length=1, max_length=64)
    channel: str = Field(default="pinduoduo_sandbox", min_length=1, max_length=64)
    code: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(min_length=1, max_length=120)
    platform_category_id: str | None = Field(default=None, max_length=100)
    required_attributes: list[str] = Field(default_factory=list, max_length=100)
    presales_keywords: list[str] = Field(default_factory=list, max_length=100)
    aftersales_keywords: list[str] = Field(default_factory=list, max_length=100)
    restricted_claims: list[str] = Field(default_factory=list, max_length=100)


class EcommerceCategoryProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    platform_category_id: str | None = Field(default=None, max_length=100)
    required_attributes: list[str] | None = Field(default=None, max_length=100)
    presales_keywords: list[str] | None = Field(default=None, max_length=100)
    aftersales_keywords: list[str] | None = Field(default=None, max_length=100)
    restricted_claims: list[str] | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, pattern=r"^(ACTIVE|DISABLED)$")


class EcommerceCategoryProfileView(BaseModel):
    id: UUID
    business_unit_id: str
    channel: str
    code: str
    name: str
    platform_category_id: str | None
    required_attributes: list[str]
    presales_keywords: list[str]
    aftersales_keywords: list[str]
    restricted_claims: list[str]
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class EcommerceProductView(BaseModel):
    id: UUID
    business_unit_id: str
    sku: str
    name: str
    category: str
    brand: str | None
    price: float
    attributes: dict[str, Any]
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class EcommerceProductImportRow(BaseModel):
    row_number: int
    sku: str
    name: str
    category: str
    brand: str
    valid: bool
    errors: list[str]
    price: float | None
    attributes: dict[str, Any]


class EcommerceProductImportPreview(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    columns: list[str]
    rows: list[EcommerceProductImportRow]


class EcommerceProductImportResult(BaseModel):
    requested_rows: int
    created_count: int
    skipped_count: int
    products: list[EcommerceProductView]
    errors: list[str]


class EcommerceProductAssetView(BaseModel):
    id: UUID
    product_id: UUID
    business_unit_id: str
    owner_employee_id: UUID | None
    asset_type: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    metadata: dict[str, Any]
    created_by: str
    created_at: datetime


class EcommerceImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)


class EcommerceImageBatchGenerateRequest(EcommerceImageGenerateRequest):
    count: int = Field(default=3, ge=1, le=4)


class EcommerceImageBatchGenerateResponse(BaseModel):
    items: list[EcommerceProductAssetView]


class EcommerceImageGenerationView(BaseModel):
    id: UUID
    business_unit_id: str
    product_id: UUID
    provider: str
    model_name: str
    prompt: str
    requested_count: int
    succeeded_count: int
    fallback_used: bool
    estimated_cost: float
    status: str
    error_message: str | None
    correlation_id: str
    created_at: datetime
    completed_at: datetime | None


class EcommerceImageGenerationListResponse(BaseModel):
    items: list[EcommerceImageGenerationView]
    total_images: int
    estimated_cost: float


class EcommerceVideoRenderJobView(BaseModel):
    id: UUID
    business_unit_id: str
    product_id: UUID
    listing_task_id: UUID
    generation_id: str
    status: str
    progress: int
    scene_count: int
    duration_seconds: float
    asset_id: UUID | None
    background_music_asset_id: UUID | None
    background_music_volume: float
    error_message: str | None
    correlation_id: str
    created_by: str
    retry_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class EcommerceVideoRenderJobListResponse(BaseModel):
    items: list[EcommerceVideoRenderJobView]
    total: int


class EcommerceVideoRenderJobCreate(BaseModel):
    background_music_asset_id: UUID | None = None
    background_music_volume: float = Field(default=0.18, ge=0, le=1)


class ChannelConnectionTestResult(BaseModel):
    configured: bool
    success: bool
    message: str
    response: dict[str, Any] = Field(default_factory=dict)


class EcommerceListingBatchCreate(BaseModel):
    product_ids: list[UUID] = Field(min_length=1, max_length=10)
    channel: str = Field(default="pinduoduo_sandbox", min_length=1, max_length=64)
    market_code: str = Field(default="CN", min_length=2, max_length=16)


class EcommerceListingBatchItemView(BaseModel):
    id: UUID
    product_id: UUID
    status: str
    listing_task_id: UUID | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class EcommerceListingBatchJobView(BaseModel):
    id: UUID
    business_unit_id: str
    channel: str
    market_code: str
    status: str
    total_count: int
    succeeded_count: int
    failed_count: int
    error_message: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    items: list[EcommerceListingBatchItemView]


class EcommerceListingBatchJobListResponse(BaseModel):
    items: list[EcommerceListingBatchJobView]
    total: int


class EcommerceOperationalMetrics(BaseModel):
    business_unit_id: str
    total_listings: int
    pending_review: int
    needs_human: int
    publishing: int
    published: int
    rejected: int
    failed: int
    publication_success_rate: float
    human_intervention_rate: float
    average_publish_seconds: float | None
    market_breakdown: dict[str, int]
    video_jobs: int
    video_succeeded: int
    video_failed: int
    video_active: int
    video_success_rate: float
    average_render_seconds: float | None
    generated_images: int
    estimated_image_cost: float


class EcommerceListingCreate(BaseModel):
    product_id: UUID
    channel: str = Field(default="local_shop", min_length=1, max_length=64)
    market_code: str = Field(default="CN", min_length=2, max_length=16)
    sale_price: float | None = Field(default=None, ge=0)


class EcommerceListingReview(BaseModel):
    expected_version: int = Field(ge=1)
    decision: str
    reason_code: str = Field(default="ECOMMERCE_REVIEWED", max_length=64)


class EcommerceListingContentUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    selling_points: list[str] = Field(min_length=1, max_length=5)
    detail_description: str = Field(min_length=1, max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=10)


class EcommerceListingRetryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason_code: str = Field(default="MANUAL_PUBLISH_RETRY", max_length=64)


class EcommerceListingListItem(BaseModel):
    id: UUID
    product_id: UUID
    sku: str
    product_name: str
    channel: str
    market_code: str
    owner_employee_id: UUID | None
    locale: str
    currency: str
    sale_price: float
    status: str
    risk_level: str
    version: int
    human_reason: str | None
    external_listing_id: str | None
    created_at: datetime
    updated_at: datetime


class EcommerceListingListResponse(BaseModel):
    items: list[EcommerceListingListItem]
    total: int


class EcommerceListingDetail(EcommerceListingListItem):
    business_unit_id: str
    product_category: str
    content: dict[str, Any]
    compliance: dict[str, Any]
    citations: list[dict[str, Any]]
    generator_provider: str
    generator_model: str
    error_message: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    published_at: datetime | None


class EcommerceListingMutation(BaseModel):
    task_id: UUID
    version: int
    status: str
    message: str
