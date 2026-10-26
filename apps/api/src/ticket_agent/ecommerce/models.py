from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class EcommerceProduct(Base):
    __tablename__ = "ecommerce_products"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "sku",
            name="uq_ecommerce_product_unit_sku",
        ),
        Index("ix_ecommerce_products_unit_status", "business_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120))
    price: Mapped[float] = mapped_column(Float, nullable=False)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), default="READY", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class EcommerceCategoryProfile(Base):
    __tablename__ = "ecommerce_category_profiles"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "channel",
            "code",
            name="uq_ecommerce_category_business_code",
        ),
        Index("ix_ecommerce_categories_unit_status", "business_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform_category_id: Mapped[str | None] = mapped_column(String(100))
    required_attributes_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    presales_keywords_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    aftersales_keywords_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    restricted_claims_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class EcommerceListingTask(Base):
    __tablename__ = "ecommerce_listing_tasks"
    __table_args__ = (
        Index("ix_ecommerce_listing_unit_status", "business_unit_id", "status"),
        Index("ix_ecommerce_listing_product_time", "product_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    market_code: Mapped[str] = mapped_column(
        String(16),
        default="CN",
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(
        String(20),
        default="zh-CN",
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="CNY",
        nullable=False,
    )
    sale_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(8), default="R0", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    compliance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    generator_provider: Mapped[str] = mapped_column(
        String(64),
        default="local",
        nullable=False,
    )
    generator_model: Mapped[str] = mapped_column(
        String(160),
        default="ecommerce-listing-template-v1",
        nullable=False,
    )
    human_reason: Mapped[str | None] = mapped_column(String(64))
    external_listing_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(2000))
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class EcommerceProductAsset(Base):
    __tablename__ = "ecommerce_product_assets"
    __table_args__ = (
        Index(
            "ix_ecommerce_assets_product_time",
            "product_id",
            "created_at",
        ),
        Index("ix_ecommerce_assets_unit_type", "business_unit_id", "asset_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="READY", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class EcommerceImageGeneration(Base):
    __tablename__ = "ecommerce_image_generations"
    __table_args__ = (
        Index(
            "ix_ecommerce_image_generations_unit_time",
            "business_unit_id",
            "created_at",
        ),
        Index(
            "ix_ecommerce_image_generations_product_time",
            "product_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt: Mapped[str] = mapped_column(String(2000), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(default=False, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2000))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EcommerceVideoRenderJob(Base):
    __tablename__ = "ecommerce_video_render_jobs"
    __table_args__ = (
        Index(
            "ix_ecommerce_video_jobs_task_time",
            "listing_task_id",
            "created_at",
        ),
        Index(
            "ix_ecommerce_video_jobs_unit_status",
            "business_unit_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    listing_task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_listing_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    generation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_asset_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scene_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    asset_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_product_assets.id", ondelete="SET NULL"),
    )
    background_music_asset_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_product_assets.id", ondelete="SET NULL"),
    )
    background_music_volume: Mapped[float] = mapped_column(
        Float,
        default=0.18,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(String(2000))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class EcommerceListingBatchJob(Base):
    __tablename__ = "ecommerce_listing_batch_jobs"
    __table_args__ = (
        Index(
            "ix_ecommerce_listing_batches_unit_time",
            "business_unit_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    market_code: Mapped[str] = mapped_column(
        String(16),
        default="CN",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="QUEUED",
        nullable=False,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(String(2000))
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EcommerceListingBatchItem(Base):
    __tablename__ = "ecommerce_listing_batch_items"
    __table_args__ = (
        Index(
            "ix_ecommerce_listing_batch_items_job",
            "batch_job_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_listing_batch_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="QUEUED",
        nullable=False,
    )
    listing_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ecommerce_listing_tasks.id", ondelete="SET NULL"),
    )
    error_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
