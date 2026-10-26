import io
import json
import re
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.ecommerce.adapters import (
    EcommerceChannelError,
    EcommerceListingPayload,
    get_ecommerce_channel_adapter,
)
from ticket_agent.ecommerce.content_generation import (
    ContentGenerationError,
    get_listing_content_generator,
)
from ticket_agent.ecommerce.image_generation import (
    ImageGenerationError,
    ImageVisualAuditError,
    get_product_image_generator,
    get_product_image_visual_auditor,
)
from ticket_agent.ecommerce.markets import MarketProfile, get_market_profile
from ticket_agent.ecommerce.media import inspect_product_media
from ticket_agent.ecommerce.models import (
    EcommerceCategoryProfile,
    EcommerceImageGeneration,
    EcommerceListingBatchItem,
    EcommerceListingBatchJob,
    EcommerceListingTask,
    EcommerceProduct,
    EcommerceProductAsset,
    EcommerceVideoRenderJob,
)
from ticket_agent.ecommerce.product_import import (
    parse_category_product_import_csv,
    parse_product_import_csv,
)
from ticket_agent.ecommerce.schemas import (
    EcommerceCategoryProfileCreate,
    EcommerceCategoryProfileUpdate,
    EcommerceCategoryProfileView,
    EcommerceImageBatchGenerateRequest,
    EcommerceImageGenerateRequest,
    EcommerceImageGenerationListResponse,
    EcommerceImageGenerationView,
    EcommerceListingBatchCreate,
    EcommerceListingBatchItemView,
    EcommerceListingBatchJobListResponse,
    EcommerceListingBatchJobView,
    EcommerceListingContentUpdate,
    EcommerceListingCreate,
    EcommerceListingDetail,
    EcommerceListingListItem,
    EcommerceListingRetryRequest,
    EcommerceListingReview,
    EcommerceOperationalMetrics,
    EcommerceProductAssetView,
    EcommerceProductCreate,
    EcommerceProductImportPreview,
    EcommerceProductImportResult,
    EcommerceProductImportRow,
    EcommerceProductView,
    EcommerceVideoRenderJobCreate,
    EcommerceVideoRenderJobListResponse,
    EcommerceVideoRenderJobView,
)
from ticket_agent.ecommerce.subtitles import build_storyboard_webvtt
from ticket_agent.ecommerce.tts_generation import (
    TTSGenerationError,
    assemble_scene_audio,
    get_speech_generator,
)
from ticket_agent.ecommerce.video_render import (
    StoryboardRenderError,
    burn_storyboard_subtitles,
    mux_storyboard_audio,
    render_storyboard_video,
)
from ticket_agent.knowledge.product_sync import sync_product_knowledge
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.redaction import redact_sensitive_text
from ticket_agent.shared.settings import get_settings
from ticket_agent.storage.factory import get_object_storage
from ticket_agent.storage.types import ObjectStorage, ObjectStorageError
from ticket_agent.tickets.models import OutboxEvent


class EcommerceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_category_profile(
        self,
        payload: EcommerceCategoryProfileCreate,
        *,
        actor_id: str,
    ) -> EcommerceCategoryProfile:
        profile = EcommerceCategoryProfile(
            business_unit_id=payload.business_unit_id,
            channel=payload.channel,
            code=payload.code,
            name=payload.name.strip(),
            platform_category_id=payload.platform_category_id,
            required_attributes_json=payload.required_attributes,
            presales_keywords_json=payload.presales_keywords,
            aftersales_keywords_json=payload.aftersales_keywords,
            restricted_claims_json=payload.restricted_claims,
            status="ACTIVE",
            created_by=actor_id,
        )
        self.session.add(profile)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="ECOMMERCE_CATEGORY_EXISTS",
                title="Category profile already exists",
                detail="Category code must be unique within business unit and channel.",
            ) from exc
        self.session.refresh(profile)
        return profile

    def list_category_profiles(
        self, business_unit_id: str
    ) -> list[EcommerceCategoryProfile]:
        return list(
            self.session.scalars(
                select(EcommerceCategoryProfile)
                .where(
                    EcommerceCategoryProfile.business_unit_id == business_unit_id
                )
                .order_by(EcommerceCategoryProfile.name)
            ).all()
        )

    def _category_profile_for_product(
        self,
        product: EcommerceProduct,
        channel: str,
    ) -> EcommerceCategoryProfile | None:
        return self.session.scalar(
            select(EcommerceCategoryProfile).where(
                EcommerceCategoryProfile.business_unit_id
                == product.business_unit_id,
                EcommerceCategoryProfile.channel == channel,
                EcommerceCategoryProfile.name == product.category,
                EcommerceCategoryProfile.status == "ACTIVE",
            )
        )

    def get_category_profile(
        self, profile_id: UUID
    ) -> EcommerceCategoryProfile:
        profile = self.session.get(EcommerceCategoryProfile, profile_id)
        if profile is None:
            raise ApiProblem(
                status_code=404,
                code="ECOMMERCE_CATEGORY_NOT_FOUND",
                title="Category profile not found",
                detail=f"Category profile {profile_id} does not exist.",
            )
        return profile

    def update_category_profile(
        self,
        profile_id: UUID,
        payload: EcommerceCategoryProfileUpdate,
    ) -> EcommerceCategoryProfile:
        profile = self.session.get(EcommerceCategoryProfile, profile_id)
        if profile is None:
            raise ApiProblem(
                status_code=404,
                code="ECOMMERCE_CATEGORY_NOT_FOUND",
                title="Category profile not found",
                detail=f"Category profile {profile_id} does not exist.",
            )
        for field, column in (
            ("name", "name"),
            ("platform_category_id", "platform_category_id"),
            ("required_attributes", "required_attributes_json"),
            ("presales_keywords", "presales_keywords_json"),
            ("aftersales_keywords", "aftersales_keywords_json"),
            ("restricted_claims", "restricted_claims_json"),
            ("status", "status"),
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(profile, column, value)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    def category_profile_view(
        self, profile: EcommerceCategoryProfile
    ) -> EcommerceCategoryProfileView:
        return EcommerceCategoryProfileView(
            id=profile.id,
            business_unit_id=profile.business_unit_id,
            channel=profile.channel,
            code=profile.code,
            name=profile.name,
            platform_category_id=profile.platform_category_id,
            required_attributes=profile.required_attributes_json,
            presales_keywords=profile.presales_keywords_json,
            aftersales_keywords=profile.aftersales_keywords_json,
            restricted_claims=profile.restricted_claims_json,
            status=profile.status,
            created_by=profile.created_by,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    def create_product(
        self,
        payload: EcommerceProductCreate,
        *,
        actor_id: str,
        correlation_id: str | None = None,
    ) -> EcommerceProduct:
        product = EcommerceProduct(
            business_unit_id=payload.business_unit_id,
            sku=payload.sku.strip(),
            name=payload.name.strip(),
            category=payload.category.strip(),
            brand=payload.brand.strip() if payload.brand else None,
            price=payload.price,
            attributes_json=payload.attributes,
            status="READY",
            created_by=actor_id,
        )
        self.session.add(product)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="ECOMMERCE_PRODUCT_EXISTS",
                title="Product SKU already exists",
                detail=f"SKU {payload.sku} already exists in this business unit.",
            ) from exc
        self.session.refresh(product)
        sync_product_knowledge(
            self.session,
            product,
            actor_id=actor_id,
            correlation_id=correlation_id or f"product-create:{product.id}",
        )
        return product

    def list_products(self, business_unit_id: str) -> list[EcommerceProduct]:
        return list(
            self.session.scalars(
                select(EcommerceProduct)
                .where(EcommerceProduct.business_unit_id == business_unit_id)
                .order_by(EcommerceProduct.updated_at.desc())
            ).all()
        )

    def get_product(self, product_id: UUID) -> EcommerceProduct:
        product = self.session.get(EcommerceProduct, product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The requested product does not exist.",
            )
        return product

    def preview_product_import(
        self,
        csv_data: bytes,
        *,
        business_unit_id: str,
        category_profile_id: UUID | None = None,
    ) -> EcommerceProductImportPreview:
        existing_skus = {
            product.sku.upper()
            for product in self.list_products(business_unit_id)
        }
        if category_profile_id:
            profile = self.get_category_profile(category_profile_id)
            parsed = parse_category_product_import_csv(
                csv_data,
                existing_skus=existing_skus,
                category_name=profile.name,
                required_attributes=profile.required_attributes_json,
            )
        else:
            parsed = parse_product_import_csv(
                csv_data,
                existing_skus=existing_skus,
            )
        rows = [
            EcommerceProductImportRow(
                row_number=row.row_number,
                sku=row.sku,
                name=row.name,
                category=row.category,
                brand=row.brand,
                valid=row.valid,
                errors=row.errors,
                price=row.price,
                attributes=row.attributes,
            )
            for row in parsed.rows
        ]
        valid_rows = sum(1 for row in rows if row.valid)
        return EcommerceProductImportPreview(
            total_rows=len(rows),
            valid_rows=valid_rows,
            invalid_rows=len(rows) - valid_rows,
            columns=parsed.columns,
            rows=rows,
        )

    def import_products(
        self,
        csv_data: bytes,
        *,
        business_unit_id: str,
        actor_id: str,
        correlation_id: str | None = None,
        category_profile_id: UUID | None = None,
    ) -> EcommerceProductImportResult:
        preview = self.preview_product_import(
            csv_data,
            business_unit_id=business_unit_id,
            category_profile_id=category_profile_id,
        )
        created: list[EcommerceProductView] = []
        errors: list[str] = []
        for row in preview.rows:
            if not row.valid or row.price is None:
                continue
            try:
                product = self.create_product(
                    EcommerceProductCreate(
                        business_unit_id=business_unit_id,
                        sku=row.sku,
                        name=row.name,
                        category=row.category,
                        brand=row.brand or None,
                        price=row.price,
                        attributes=row.attributes,
                    ),
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
            except ApiProblem as exc:
                errors.append(
                    f"Row {row.row_number} ({row.sku}): {exc.detail}"
                )
                continue
            created.append(self.product_view(product))
        return EcommerceProductImportResult(
            requested_rows=preview.total_rows,
            created_count=len(created),
            skipped_count=preview.total_rows - len(created),
            products=created,
            errors=errors,
        )

    def create_asset(
        self,
        product_id: UUID,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        actor_id: str,
        correlation_id: str,
        storage: ObjectStorage | None = None,
        extra_metadata: dict[str, object] | None = None,
    ) -> EcommerceProductAsset:
        product = self.session.get(EcommerceProduct, product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The requested product does not exist.",
            )
        asset_type = _asset_type(content_type)
        if asset_type is None:
            raise ApiProblem(
                status_code=415,
                code="UNSUPPORTED_ASSET_TYPE",
                title="Unsupported asset type",
                detail=(
                    "Only JPEG, PNG, WebP, MP4, WebM, QuickTime, WAV, MP3, "
                    "and WebVTT subtitles are supported."
                ),
            )
        if not data:
            raise ApiProblem(
                status_code=422,
                code="EMPTY_FILE",
                title="Asset is empty",
                detail="Upload a non-empty file.",
            )
        if len(data) > 100 * 1024 * 1024:
            raise ApiProblem(
                status_code=422,
                code="FILE_TOO_LARGE",
                title="Asset is too large",
                detail="Ecommerce assets must not exceed 100 MB.",
            )

        asset_id = uuid4()
        safe_filename = Path(filename).name
        object_key = (
            f"ecommerce/{product.business_unit_id}/{product.id}/"
            f"{asset_id}/{safe_filename}"
        )
        storage = storage or get_object_storage()
        try:
            storage.put_object(
                key=object_key,
                data=data,
                content_type=content_type,
            )
        except ObjectStorageError as exc:
            raise ApiProblem(
                status_code=503,
                code="OBJECT_STORAGE_UNAVAILABLE",
                title="Object storage is unavailable",
                detail="Unable to persist the product asset.",
                retryable=True,
            ) from exc
        metadata = inspect_product_media(data, content_type)
        metadata.update(extra_metadata or {})
        asset = EcommerceProductAsset(
            id=asset_id,
            product_id=product.id,
            business_unit_id=product.business_unit_id,
            owner_employee_id=self._operation_employee_id(
                product.business_unit_id,
                "ecommerce_visual_creator",
            ),
            asset_type=asset_type,
            filename=safe_filename,
            content_type=content_type,
            size_bytes=len(data),
            object_key=object_key,
            status="READY",
            metadata_json=metadata,
            created_by=actor_id,
        )
        self.session.add(asset)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.asset.uploaded",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_product",
            resource_id=product.id,
            action="upload_asset",
            decision="EXECUTED",
            payload={
                "asset_id": str(asset.id),
                "asset_type": asset_type,
                "filename": safe_filename,
                "size_bytes": len(data),
            },
        )
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def generate_product_image(
        self,
        product_id: UUID,
        payload: EcommerceImageGenerateRequest,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> EcommerceProductAsset:
        assets = self.generate_product_images(
            product_id,
            EcommerceImageBatchGenerateRequest(
                prompt=payload.prompt,
                count=1,
            ),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return assets[0]

    def generate_product_images(
        self,
        product_id: UUID,
        payload: EcommerceImageBatchGenerateRequest,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> list[EcommerceProductAsset]:
        product = self.session.get(EcommerceProduct, product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The requested product does not exist.",
            )
        settings = get_settings()
        generator = get_product_image_generator()
        safe_prompt = redact_sensitive_text(payload.prompt)
        generation = EcommerceImageGeneration(
            business_unit_id=product.business_unit_id,
            product_id=product.id,
            provider=settings.ecommerce_image_provider,
            model_name=(
                settings.ecommerce_image_model_name
                if settings.ecommerce_image_provider == "openai_compatible"
                else "local-product-image-v1"
            ),
            prompt=safe_prompt,
            requested_count=payload.count,
            succeeded_count=0,
            fallback_used=False,
            estimated_cost=0.0,
            status="RUNNING",
            correlation_id=correlation_id,
        )
        self.session.add(generation)
        self.session.commit()
        generation_id = generation.id
        assets: list[EcommerceProductAsset] = []
        try:
            for variant_index in range(payload.count):
                generated = generator.generate(
                    prompt=(
                        f"{payload.prompt}\n"
                        f"生成候选变体 {variant_index + 1}，保持主体和风格一致。"
                    )
                )
                asset = self.create_asset(
                    product.id,
                    filename=(
                        f"ai-generated-{uuid4().hex[:10]}-{variant_index + 1}.png"
                    ),
                    content_type=generated.content_type,
                    data=generated.data,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    extra_metadata={
                        "source": "AI_GENERATED",
                        "prompt": safe_prompt,
                        "variant_index": variant_index + 1,
                        "generator_provider": generated.provider,
                        "generator_model": generated.model_name,
                        "fallback_used": generated.fallback_used,
                        **self._visual_audit_metadata(
                            generated.data,
                            generated.content_type,
                        ),
                    },
                )
                assets.append(asset)
        except (ImageGenerationError, ApiProblem) as exc:
            self.session.rollback()
            failed = self.session.get(EcommerceImageGeneration, generation_id)
            if failed is not None:
                failed.status = "FAILED"
                failed.succeeded_count = len(assets)
                failed.error_message = str(exc)[:2000]
                failed.completed_at = datetime.now(UTC)
                self.session.commit()
            if isinstance(exc, ApiProblem):
                raise
            raise ApiProblem(
                status_code=502,
                code="IMAGE_GENERATION_FAILED",
                title="Image generation failed",
                detail=str(exc),
                retryable=True,
            ) from exc
        completed = self.session.get(EcommerceImageGeneration, generation_id)
        if completed is None:
            raise ApiProblem(
                status_code=500,
                code="IMAGE_GENERATION_AUDIT_MISSING",
                title="Image generation audit is missing",
                detail="Generation usage could not be finalized.",
            )
        completed.provider = assets[0].metadata_json.get(
            "generator_provider",
            completed.provider,
        )
        completed.model_name = str(
            assets[0].metadata_json.get(
                "generator_model",
                completed.model_name,
            )
        )
        completed.succeeded_count = len(assets)
        completed.fallback_used = any(
            asset.metadata_json.get("fallback_used") is True for asset in assets
        )
        completed.estimated_cost = (
            len(assets) * settings.ecommerce_image_cost_per_image
        )
        completed.status = "SUCCEEDED"
        completed.completed_at = datetime.now(UTC)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.assets.generated",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_creative",
            resource_type="ecommerce_product",
            resource_id=product.id,
            action="generate_image_candidates",
            decision="EXECUTED",
            payload={
                "generation_id": str(completed.id),
                "count": len(assets),
                "asset_ids": [str(asset.id) for asset in assets],
                "estimated_cost": completed.estimated_cost,
            },
        )
        self.session.commit()
        return assets

    @staticmethod
    def _visual_audit_metadata(
        data: bytes,
        content_type: str,
    ) -> dict[str, object]:
        auditor = get_product_image_visual_auditor()
        if auditor is None:
            return {"visual_audit_status": "NOT_CONFIGURED"}
        try:
            audit = auditor.audit(data=data, content_type=content_type)
        except (ImageVisualAuditError, OSError, ValueError) as exc:
            return {
                "visual_audit_provider": "dashscope_ocr",
                "visual_audit_status": "ERROR",
                "visual_audit_error": redact_sensitive_text(str(exc))[:500],
            }
        return {
            "visual_audit_provider": audit.provider,
            "visual_audit_model": audit.model_name,
            "visual_audit_status": audit.status,
            "visual_audit_text": audit.extracted_text,
        }

    def list_image_generations(
        self,
        *,
        business_unit_id: str,
        limit: int = 50,
    ) -> EcommerceImageGenerationListResponse:
        statement = select(EcommerceImageGeneration).where(
            EcommerceImageGeneration.business_unit_id == business_unit_id
        )
        generations = list(
            self.session.scalars(
                statement.order_by(EcommerceImageGeneration.created_at.desc()).limit(
                    limit
                )
            ).all()
        )
        return EcommerceImageGenerationListResponse(
            items=[
                EcommerceImageGenerationView(
                    id=item.id,
                    business_unit_id=item.business_unit_id,
                    product_id=item.product_id,
                    provider=item.provider,
                    model_name=item.model_name,
                    prompt=item.prompt,
                    requested_count=item.requested_count,
                    succeeded_count=item.succeeded_count,
                    fallback_used=item.fallback_used,
                    estimated_cost=item.estimated_cost,
                    status=item.status,
                    error_message=item.error_message,
                    correlation_id=item.correlation_id,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                )
                for item in generations
            ],
            total_images=sum(item.succeeded_count for item in generations),
            estimated_cost=sum(item.estimated_cost for item in generations),
        )

    def operational_metrics(self, business_unit_id: str) -> EcommerceOperationalMetrics:
        tasks = self.session.scalars(
            select(EcommerceListingTask).where(
                EcommerceListingTask.business_unit_id == business_unit_id
            )
        ).all()
        jobs = self.session.scalars(
            select(EcommerceVideoRenderJob).where(
                EcommerceVideoRenderJob.business_unit_id == business_unit_id
            )
        ).all()
        image_generations = self.session.scalars(
            select(EcommerceImageGeneration).where(
                EcommerceImageGeneration.business_unit_id == business_unit_id
            )
        ).all()

        status_counts = Counter(task.status for task in tasks)
        market_breakdown = Counter(task.market_code for task in tasks)
        published = status_counts["PUBLISHED"]
        failed = status_counts["FAILED"]
        publication_terminal = published + failed
        human_interventions = sum(
            1
            for task in tasks
            if task.risk_level == "R2" or bool(task.human_reason)
        )
        publish_durations = [
            value
            for task in tasks
            if (value := _duration_seconds(task.created_at, task.published_at))
            is not None
        ]

        video_status_counts = Counter(job.status for job in jobs)
        video_succeeded = video_status_counts["SUCCEEDED"]
        video_failed = video_status_counts["FAILED"]
        video_terminal = video_succeeded + video_failed
        render_durations = [
            value
            for job in jobs
            if (value := _duration_seconds(job.started_at, job.completed_at))
            is not None
        ]

        return EcommerceOperationalMetrics(
            business_unit_id=business_unit_id,
            total_listings=len(tasks),
            pending_review=status_counts["PENDING_REVIEW"],
            needs_human=status_counts["NEEDS_HUMAN"],
            publishing=status_counts["PUBLISHING"],
            published=published,
            rejected=status_counts["REJECTED"],
            failed=failed,
            publication_success_rate=(
                round(published / publication_terminal, 4)
                if publication_terminal
                else 0.0
            ),
            human_intervention_rate=(
                round(human_interventions / len(tasks), 4) if tasks else 0.0
            ),
            average_publish_seconds=(
                round(sum(publish_durations) / len(publish_durations), 3)
                if publish_durations
                else None
            ),
            market_breakdown=dict(market_breakdown),
            video_jobs=len(jobs),
            video_succeeded=video_succeeded,
            video_failed=video_failed,
            video_active=(
                video_status_counts["QUEUED"] + video_status_counts["RUNNING"]
            ),
            video_success_rate=(
                round(video_succeeded / video_terminal, 4)
                if video_terminal
                else 0.0
            ),
            average_render_seconds=(
                round(sum(render_durations) / len(render_durations), 3)
                if render_durations
                else None
            ),
            generated_images=sum(
                generation.succeeded_count for generation in image_generations
            ),
            estimated_image_cost=round(
                sum(generation.estimated_cost for generation in image_generations),
                6,
            ),
        )

    def backfill_operation_owners(self, business_unit_id: str) -> dict[str, int]:
        listing_owner = self._operation_employee_id(
            business_unit_id,
            "ecommerce_listing_operator",
        )
        visual_owner = self._operation_employee_id(
            business_unit_id,
            "ecommerce_visual_creator",
        )
        listing_backfilled = 0
        asset_backfilled = 0
        if listing_owner is not None:
            for task in self.session.scalars(
                select(EcommerceListingTask).where(
                    EcommerceListingTask.business_unit_id == business_unit_id,
                    EcommerceListingTask.owner_employee_id.is_(None),
                )
            ).all():
                task.owner_employee_id = listing_owner
                listing_backfilled += 1
        if visual_owner is not None:
            for asset in self.session.scalars(
                select(EcommerceProductAsset).where(
                    EcommerceProductAsset.business_unit_id == business_unit_id,
                    EcommerceProductAsset.owner_employee_id.is_(None),
                )
            ).all():
                asset.owner_employee_id = visual_owner
                asset_backfilled += 1
        self.session.commit()
        return {
            "listing_tasks": listing_backfilled,
            "product_assets": asset_backfilled,
        }

    def generate_listing_storyboard(
        self,
        task_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> list[EcommerceProductAsset]:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        product = self.session.get(EcommerceProduct, task.product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The listing task product no longer exists.",
            )
        raw_scenes = task.content_json.get("short_video_script")
        if not isinstance(raw_scenes, list) or not raw_scenes:
            raise ApiProblem(
                status_code=409,
                code="STORYBOARD_SCRIPT_MISSING",
                title="Short video script is missing",
                detail="Regenerate listing content before generating a storyboard.",
            )
        scenes = [
            scene for scene in raw_scenes if isinstance(scene, dict)
        ][:8]
        settings = get_settings()
        generator = get_product_image_generator()
        generation = EcommerceImageGeneration(
            business_unit_id=task.business_unit_id,
            product_id=product.id,
            provider=settings.ecommerce_image_provider,
            model_name=(
                settings.ecommerce_image_model_name
                if settings.ecommerce_image_provider == "openai_compatible"
                else "local-product-image-v1"
            ),
            prompt=f"商品短视频分镜：{product.name}",
            requested_count=len(scenes),
            succeeded_count=0,
            fallback_used=False,
            estimated_cost=0.0,
            status="RUNNING",
            correlation_id=correlation_id,
        )
        self.session.add(generation)
        self.session.commit()
        generation_id = generation.id
        assets: list[EcommerceProductAsset] = []
        try:
            for index, scene in enumerate(scenes, start=1):
                visual = str(scene.get("visual", "商品展示"))
                line = str(scene.get("line", ""))
                seconds = str(scene.get("second", ""))
                generated = generator.generate(
                    prompt=(
                        f"{product.name}，电商短视频第 {index} 个分镜。"
                        f"画面：{visual}。文案：{line}。"
                        "竖屏构图，主体清晰，商业摄影风格。"
                        "画面中不要出现任何文字、数字、Logo、水印、标签或价格牌；"
                        "即使文案要求标注，也只展示对应产品细节。"
                    )
                )
                asset = self.create_asset(
                    product.id,
                    filename=f"storyboard-{task.id.hex[:8]}-{index}.png",
                    content_type=generated.content_type,
                    data=generated.data,
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                    extra_metadata={
                        "source": "STORYBOARD_GENERATED",
                        "listing_task_id": str(task.id),
                        "generation_id": str(generation_id),
                        "scene_index": index,
                        "scene_seconds": seconds,
                        "scene_visual": visual,
                        "scene_line": line,
                        "generator_provider": generated.provider,
                        "generator_model": generated.model_name,
                        "fallback_used": generated.fallback_used,
                        **self._visual_audit_metadata(
                            generated.data,
                            generated.content_type,
                        ),
                    },
                )
                assets.append(asset)
        except (ImageGenerationError, ApiProblem) as exc:
            self.session.rollback()
            for asset in assets:
                stored_asset = self.session.get(EcommerceProductAsset, asset.id)
                if stored_asset is not None:
                    stored_asset.status = "ARCHIVED"
            failed = self.session.get(EcommerceImageGeneration, generation_id)
            if failed is not None:
                failed.status = "FAILED"
                failed.succeeded_count = len(assets)
                failed.error_message = str(exc)[:2000]
                failed.completed_at = datetime.now(UTC)
                self.session.commit()
            if isinstance(exc, ApiProblem):
                raise
            raise ApiProblem(
                status_code=502,
                code="STORYBOARD_GENERATION_FAILED",
                title="Storyboard generation failed",
                detail=str(exc),
                retryable=True,
            ) from exc
        completed = self.session.get(EcommerceImageGeneration, generation_id)
        if completed is not None:
            completed.provider = str(
                assets[0].metadata_json.get("generator_provider", completed.provider)
            )
            completed.model_name = str(
                assets[0].metadata_json.get("generator_model", completed.model_name)
            )
            completed.succeeded_count = len(assets)
            completed.fallback_used = any(
                asset.metadata_json.get("fallback_used") is True
                for asset in assets
            )
            completed.estimated_cost = (
                len(assets) * settings.ecommerce_image_cost_per_image
            )
            completed.status = "SUCCEEDED"
            completed.completed_at = datetime.now(UTC)
        archived_count = self._archive_listing_media(
            product.id,
            task.id,
            sources=(
                "STORYBOARD_GENERATED",
                "STORYBOARD_VIDEO",
                "STORYBOARD_SUBTITLE",
                "STORYBOARD_VOICEOVER",
            ),
            keep_asset_ids={asset.id for asset in assets},
        )
        superseded_jobs = self.session.scalars(
            select(EcommerceVideoRenderJob).where(
                EcommerceVideoRenderJob.listing_task_id == task.id,
                EcommerceVideoRenderJob.status.in_(("QUEUED", "RUNNING")),
            )
        ).all()
        superseded_count = 0
        for superseded_job in superseded_jobs:
            if superseded_job.generation_id == str(generation_id):
                continue
            superseded_job.status = "FAILED"
            superseded_job.progress = 100
            superseded_job.error_message = (
                "STORYBOARD_SUPERSEDED_BY_NEW_BATCH: "
                "A newer storyboard batch replaced this render job."
            )
            superseded_job.completed_at = datetime.now(UTC)
            superseded_count += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.storyboard.generated",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_creative",
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="generate_storyboard",
            decision="EXECUTED",
            payload={
                "generation_id": str(generation_id),
                "scene_count": len(assets),
                "asset_ids": [str(asset.id) for asset in assets],
                "archived_previous_count": archived_count,
                "superseded_render_job_count": superseded_count,
            },
        )
        self.session.commit()
        return assets

    def render_listing_storyboard_video(
        self,
        task_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> EcommerceProductAsset:
        return self.render_storyboard_video_snapshot(
            task_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def render_storyboard_video_snapshot(
        self,
        task_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
        generation_id: str | None = None,
        source_asset_ids: list[str] | None = None,
        render_job_id: UUID | None = None,
        require_current_generation: bool = False,
        background_music: bytes | None = None,
        background_music_asset_id: UUID | None = None,
        background_music_volume: float = 0.18,
    ) -> EcommerceProductAsset:
        task, product, storyboard_assets, latest_generation_id = (
            self._resolve_storyboard_assets(
                task_id,
                generation_id=generation_id,
                source_asset_ids=source_asset_ids,
            )
        )
        storage = get_object_storage()
        images = [
            storage.get_object(key=asset.object_key)
            for asset in storyboard_assets
        ]
        durations = [
            _scene_duration(str(asset.metadata_json.get("scene_seconds", "")))
            for asset in storyboard_assets
        ]
        speech_generator = get_speech_generator()
        voice_tracks: list[bytes] = []
        voice_metadata: dict[str, object] = {
            "voiceover_status": "NOT_CONFIGURED"
        }
        audio_track: bytes | None = None
        if speech_generator is not None:
            try:
                for asset in storyboard_assets:
                    speech = speech_generator.generate(
                        text=str(asset.metadata_json.get("scene_line", ""))
                    )
                    voice_tracks.append(speech.data)
                    voice_metadata = {
                        "voiceover_status": "SUCCEEDED",
                        "voiceover_provider": speech.provider,
                        "voiceover_model": speech.model_name,
                        "voiceover_voice": speech.voice,
                    }
                audio_track = assemble_scene_audio(voice_tracks, durations)
            except (TTSGenerationError, OSError, ValueError) as exc:
                raise ApiProblem(
                    status_code=503,
                    code="VOICEOVER_GENERATION_FAILED",
                    title="Voiceover generation failed",
                    detail=str(exc)[:1500],
                    retryable=True,
                ) from exc
        try:
            video = render_storyboard_video(
                images,
                durations,
                ffmpeg_path=get_settings().ecommerce_ffmpeg_path,
            )
            if audio_track is not None:
                video = mux_storyboard_audio(
                    video,
                    audio_track,
                    ffmpeg_path=get_settings().ecommerce_ffmpeg_path,
                    duration_seconds=sum(durations),
                    background_music=background_music,
                    background_music_volume=background_music_volume,
                )
        except StoryboardRenderError as exc:
            raise ApiProblem(
                status_code=503,
                code="VIDEO_RENDER_FAILED",
                title="Storyboard video render failed",
                detail=str(exc)[:1500],
                retryable=True,
            ) from exc
        if require_current_generation:
            _, _, _, current_generation_id = self._resolve_storyboard_assets(task_id)
            if current_generation_id != latest_generation_id:
                raise ApiProblem(
                    status_code=409,
                    code="STORYBOARD_SUPERSEDED_BY_NEW_BATCH",
                    title="Storyboard was superseded",
                    detail=(
                        "A newer storyboard batch was generated while this video "
                        "was rendering."
                    ),
                    retryable=True,
                )
        try:
            subtitle_data, subtitle_cue_count = build_storyboard_webvtt(
                [
                    (
                        duration,
                        str(asset.metadata_json.get("scene_line", "")),
                    )
                    for asset, duration in zip(
                        storyboard_assets,
                        durations,
                        strict=True,
                    )
                ]
            )
        except ValueError as exc:
            raise ApiProblem(
                status_code=409,
                code="STORYBOARD_SUBTITLES_INVALID",
                title="Storyboard subtitles are invalid",
                detail=str(exc),
            ) from exc
        settings = get_settings()
        subtitle_burned_in = False
        if settings.ecommerce_subtitle_burn_in:
            try:
                video = burn_storyboard_subtitles(
                    video,
                    subtitle_data,
                    font_path=Path(settings.ecommerce_subtitle_font_path),
                    ffmpeg_path=settings.ecommerce_ffmpeg_path,
                )
                subtitle_burned_in = True
            except StoryboardRenderError as exc:
                raise ApiProblem(
                    status_code=503,
                    code="SUBTITLE_BURN_IN_FAILED",
                    title="Subtitle burn-in failed",
                    detail=str(exc)[:1500],
                    retryable=True,
                ) from exc
        metadata: dict[str, object] = {
            "source": "STORYBOARD_VIDEO",
            "listing_task_id": str(task.id),
            "generation_id": latest_generation_id or "legacy",
            "scene_count": len(storyboard_assets),
            "duration_seconds": round(sum(durations), 3),
            "resolution": "1080x1920",
            "renderer": "ffmpeg",
            "effect": "slow_zoom_with_fade",
            "transition_seconds": 0.2,
            "subtitle_burned_in": subtitle_burned_in,
            "background_music_asset_id": (
                str(background_music_asset_id)
                if background_music_asset_id is not None
                else None
            ),
            "background_music_volume": background_music_volume,
            "audio_mix": (
                "voiceover_with_ducking"
                if background_music is not None and audio_track is not None
                else "voiceover_only"
                if audio_track is not None
                else "silent"
            ),
            **voice_metadata,
        }
        if render_job_id is not None:
            metadata["render_job_id"] = str(render_job_id)
        asset = self.create_asset(
            product.id,
            filename=f"storyboard-{task.id.hex[:8]}-preview.mp4",
            content_type="video/mp4",
            data=video,
            actor_id=actor_id,
            correlation_id=correlation_id,
            extra_metadata=metadata,
        )
        voiceover_asset: EcommerceProductAsset | None = None
        if audio_track is not None:
            voiceover_asset = self.create_asset(
                product.id,
                filename=f"storyboard-{task.id.hex[:8]}-voiceover.wav",
                content_type="audio/wav",
                data=audio_track,
                actor_id=actor_id,
                correlation_id=correlation_id,
                extra_metadata={
                    "source": "STORYBOARD_VOICEOVER",
                    "listing_task_id": str(task.id),
                    "generation_id": latest_generation_id or "legacy",
                    "render_job_id": (
                        str(render_job_id) if render_job_id is not None else None
                    ),
                    "video_asset_id": str(asset.id),
                    "duration_seconds": round(sum(durations), 3),
                    **voice_metadata,
                },
            )
        subtitle_asset = self.create_asset(
            product.id,
            filename=f"storyboard-{task.id.hex[:8]}-preview.vtt",
            content_type="text/vtt",
            data=subtitle_data,
            actor_id=actor_id,
            correlation_id=correlation_id,
            extra_metadata={
                "source": "STORYBOARD_SUBTITLE",
                "listing_task_id": str(task.id),
                "generation_id": latest_generation_id or "legacy",
                "render_job_id": (
                    str(render_job_id) if render_job_id is not None else None
                ),
                "video_asset_id": str(asset.id),
                "cue_count": subtitle_cue_count,
                "duration_seconds": round(sum(durations), 3),
                "language": task.locale,
            },
        )
        video_metadata = dict(asset.metadata_json)
        video_metadata["subtitle_asset_id"] = str(subtitle_asset.id)
        if voiceover_asset is not None:
            video_metadata["voiceover_asset_id"] = str(voiceover_asset.id)
        asset.metadata_json = video_metadata
        archived_count = self._archive_listing_media(
            product.id,
            task.id,
            sources=(
                "STORYBOARD_VIDEO",
                "STORYBOARD_SUBTITLE",
                "STORYBOARD_VOICEOVER",
            ),
            keep_asset_ids={
                asset.id,
                subtitle_asset.id,
                *({voiceover_asset.id} if voiceover_asset is not None else set()),
            },
        )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.storyboard.video_rendered",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_creative",
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="render_storyboard_video",
            decision="EXECUTED",
            payload={
                "asset_id": str(asset.id),
                "scene_count": len(storyboard_assets),
                "duration_seconds": round(sum(durations), 3),
                "archived_previous_count": archived_count,
                "subtitle_asset_id": str(subtitle_asset.id),
                "subtitle_cue_count": subtitle_cue_count,
                "voiceover_asset_id": (
                    str(voiceover_asset.id)
                    if voiceover_asset is not None
                    else None
                ),
                "render_job_id": (
                    str(render_job_id) if render_job_id is not None else None
                ),
            },
        )
        self.session.commit()
        return asset

    def _resolve_storyboard_assets(
        self,
        task_id: UUID,
        *,
        generation_id: str | None = None,
        source_asset_ids: list[str] | None = None,
    ) -> tuple[
        EcommerceListingTask,
        EcommerceProduct,
        list[EcommerceProductAsset],
        str,
    ]:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        product = self.session.get(EcommerceProduct, task.product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The listing task product no longer exists.",
            )

        if source_asset_ids:
            try:
                asset_ids = [UUID(asset_id) for asset_id in source_asset_ids]
            except ValueError as exc:
                raise ApiProblem(
                    status_code=409,
                    code="STORYBOARD_ASSETS_INVALID",
                    title="Storyboard assets are invalid",
                    detail="The render job contains an invalid storyboard snapshot.",
                ) from exc
            rows = self.session.scalars(
                select(EcommerceProductAsset).where(
                    EcommerceProductAsset.id.in_(asset_ids),
                    EcommerceProductAsset.product_id == product.id,
                )
            ).all()
            by_id = {asset.id: asset for asset in rows}
            storyboard_assets = [
                by_id[asset_id] for asset_id in asset_ids if asset_id in by_id
            ]
            if len(storyboard_assets) != len(asset_ids):
                raise ApiProblem(
                    status_code=409,
                    code="STORYBOARD_ASSETS_UNAVAILABLE",
                    title="Storyboard assets are unavailable",
                    detail="One or more storyboard images no longer exist.",
                )
            resolved_generation_id = generation_id or "legacy"
        else:
            candidates = [
                asset
                for asset in self.list_assets(
                    product.id,
                    business_unit_id=product.business_unit_id,
                )
                if asset.asset_type == "IMAGE"
                and asset.metadata_json.get("listing_task_id") == str(task.id)
                and asset.metadata_json.get("source") == "STORYBOARD_GENERATED"
            ]
            candidates.sort(key=lambda item: item.created_at, reverse=True)
            resolved_generation_id = next(
                (
                    str(asset.metadata_json["generation_id"])
                    for asset in candidates
                    if asset.metadata_json.get("generation_id")
                ),
                "legacy",
            )
            if resolved_generation_id != "legacy":
                storyboard_assets = [
                    asset
                    for asset in candidates
                    if asset.metadata_json.get("generation_id")
                    == resolved_generation_id
                ]
            else:
                # Legacy rows are newest first. The first repeated scene belongs
                # to an older batch.
                seen_scene_indexes: set[str] = set()
                storyboard_assets = []
                for asset in candidates:
                    scene_index = str(asset.metadata_json.get("scene_index", ""))
                    if scene_index in seen_scene_indexes:
                        break
                    seen_scene_indexes.add(scene_index)
                    storyboard_assets.append(asset)

        storyboard_assets.sort(
            key=lambda item: int(item.metadata_json.get("scene_index", 0))
        )
        if not storyboard_assets:
            raise ApiProblem(
                status_code=409,
                code="STORYBOARD_NOT_GENERATED",
                title="Storyboard is not ready",
                detail="Generate storyboard images before rendering a video.",
            )
        return task, product, storyboard_assets, resolved_generation_id

    def create_video_render_job(
        self,
        task_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
        options: EcommerceVideoRenderJobCreate | None = None,
    ) -> tuple[EcommerceVideoRenderJob, OutboxEvent | None]:
        options = options or EcommerceVideoRenderJobCreate()
        task, product, storyboard_assets, generation_id = (
            self._resolve_storyboard_assets(task_id)
        )
        visual_review_assets = [
            asset
            for asset in storyboard_assets
            if asset.metadata_json.get("visual_audit_status")
            in {"NEEDS_REVIEW", "ERROR"}
        ]
        if visual_review_assets:
            raise ApiProblem(
                status_code=409,
                code="STORYBOARD_VISUAL_REVIEW_REQUIRED",
                title="Storyboard requires visual review",
                detail=(
                    f"{len(visual_review_assets)} storyboard images contain "
                    "unexpected text or failed visual audit."
                ),
                retryable=False,
            )
        source_asset_ids = [str(asset.id) for asset in storyboard_assets]
        active_jobs = self.session.scalars(
            select(EcommerceVideoRenderJob)
            .where(
                EcommerceVideoRenderJob.listing_task_id == task.id,
                EcommerceVideoRenderJob.status.in_(("QUEUED", "RUNNING")),
            )
            .order_by(EcommerceVideoRenderJob.created_at.desc())
        ).all()
        for active_job in active_jobs:
            if (
                active_job.generation_id == generation_id
                and active_job.source_asset_ids_json == source_asset_ids
                and active_job.background_music_asset_id
                == options.background_music_asset_id
                and active_job.background_music_volume
                == options.background_music_volume
            ):
                return active_job, None

        if options.background_music_asset_id is not None:
            music_asset = self.session.get(
                EcommerceProductAsset,
                options.background_music_asset_id,
            )
            if (
                music_asset is None
                or music_asset.product_id != product.id
                or music_asset.business_unit_id != product.business_unit_id
                or music_asset.asset_type != "AUDIO"
                or music_asset.status != "READY"
            ):
                raise ApiProblem(
                    status_code=409,
                    code="INVALID_BACKGROUND_MUSIC",
                    title="Background music is invalid",
                    detail=(
                        "Select a READY audio asset from the same product."
                    ),
                )

        durations = [
            _scene_duration(str(asset.metadata_json.get("scene_seconds", "")))
            for asset in storyboard_assets
        ]
        job = EcommerceVideoRenderJob(
            business_unit_id=task.business_unit_id,
            product_id=product.id,
            listing_task_id=task.id,
            generation_id=generation_id,
            source_asset_ids_json=source_asset_ids,
            status="QUEUED",
            progress=0,
            scene_count=len(storyboard_assets),
            duration_seconds=round(sum(durations), 3),
            background_music_asset_id=options.background_music_asset_id,
            background_music_volume=options.background_music_volume,
            correlation_id=correlation_id,
            created_by=actor_id,
        )
        self.session.add(job)
        self.session.flush()
        outbox_event = self._create_video_render_outbox(job, correlation_id)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.storyboard.video_job.queued",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="queue_storyboard_video",
            decision="EXECUTED",
            payload={
                "job_id": str(job.id),
                "generation_id": generation_id,
                "scene_count": len(storyboard_assets),
                "duration_seconds": round(sum(durations), 3),
                "background_music_asset_id": (
                    str(options.background_music_asset_id)
                    if options.background_music_asset_id
                    else None
                ),
            },
        )
        self.session.commit()
        self.session.refresh(job)
        self.session.refresh(outbox_event)
        return job, outbox_event

    def retry_video_render_job(
        self,
        job_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[EcommerceVideoRenderJob, OutboxEvent | None]:
        job = self.session.scalar(
            select(EcommerceVideoRenderJob)
            .where(EcommerceVideoRenderJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Render job not found",
                detail="The requested video render job does not exist.",
            )
        if job.status in {"QUEUED", "RUNNING"}:
            return job, None
        if job.status != "FAILED":
            raise ApiProblem(
                status_code=409,
                code="RENDER_JOB_NOT_RETRYABLE",
                title="Render job cannot be retried",
                detail="Only failed render jobs can be retried.",
            )
        if (job.error_message or "").startswith(
            "STORYBOARD_SUPERSEDED_BY_NEW_BATCH:"
        ):
            _, _, current_assets, current_generation_id = (
                self._resolve_storyboard_assets(job.listing_task_id)
            )
            durations = [
                _scene_duration(
                    str(asset.metadata_json.get("scene_seconds", ""))
                )
                for asset in current_assets
            ]
            job.generation_id = current_generation_id
            job.source_asset_ids_json = [
                str(asset.id) for asset in current_assets
            ]
            job.scene_count = len(current_assets)
            job.duration_seconds = round(sum(durations), 3)
        job.status = "QUEUED"
        job.progress = 0
        job.error_message = None
        job.asset_id = None
        job.started_at = None
        job.completed_at = None
        job.retry_count += 1
        outbox_event = self._create_video_render_outbox(job, correlation_id)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.storyboard.video_job.retry_requested",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=job.listing_task_id,
            action="retry_storyboard_video",
            decision="EXECUTED",
            payload={"job_id": str(job.id), "retry_count": job.retry_count},
        )
        self.session.commit()
        self.session.refresh(job)
        self.session.refresh(outbox_event)
        return job, outbox_event

    def list_video_render_jobs(
        self,
        task_id: UUID,
        *,
        limit: int = 20,
    ) -> EcommerceVideoRenderJobListResponse:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        jobs = self.session.scalars(
            select(EcommerceVideoRenderJob)
            .where(EcommerceVideoRenderJob.listing_task_id == task_id)
            .order_by(EcommerceVideoRenderJob.created_at.desc())
            .limit(limit)
        ).all()
        total = self.session.scalar(
            select(func.count())
            .select_from(EcommerceVideoRenderJob)
            .where(EcommerceVideoRenderJob.listing_task_id == task_id)
        ) or 0
        return EcommerceVideoRenderJobListResponse(
            items=[self.video_render_job_view(job) for job in jobs],
            total=total,
        )

    def get_video_render_job(self, job_id: UUID) -> EcommerceVideoRenderJob:
        job = self.session.get(EcommerceVideoRenderJob, job_id)
        if job is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Render job not found",
                detail="The requested video render job does not exist.",
            )
        return job

    def video_render_job_view(
        self,
        job: EcommerceVideoRenderJob,
    ) -> EcommerceVideoRenderJobView:
        return EcommerceVideoRenderJobView(
            id=job.id,
            business_unit_id=job.business_unit_id,
            product_id=job.product_id,
            listing_task_id=job.listing_task_id,
            generation_id=job.generation_id,
            status=job.status,
            progress=job.progress,
            scene_count=job.scene_count,
            duration_seconds=job.duration_seconds,
            asset_id=job.asset_id,
            background_music_asset_id=job.background_music_asset_id,
            background_music_volume=job.background_music_volume,
            error_message=job.error_message,
            correlation_id=job.correlation_id,
            created_by=job.created_by,
            retry_count=job.retry_count,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            updated_at=job.updated_at,
        )

    def _create_video_render_outbox(
        self,
        job: EcommerceVideoRenderJob,
        correlation_id: str,
    ) -> OutboxEvent:
        event = OutboxEvent(
            aggregate_type="ecommerce_video_render_job",
            aggregate_id=job.id,
            event_type="ecommerce.storyboard.video_render",
            payload_json={
                "job_id": str(job.id),
                "correlation_id": correlation_id,
            },
        )
        self.session.add(event)
        return event

    def _archive_listing_media(
        self,
        product_id: UUID,
        listing_task_id: UUID,
        *,
        sources: tuple[str, ...],
        keep_asset_ids: set[UUID],
    ) -> int:
        assets = self.session.scalars(
            select(EcommerceProductAsset).where(
                EcommerceProductAsset.product_id == product_id,
                EcommerceProductAsset.status != "ARCHIVED",
            )
        ).all()
        archived_count = 0
        for asset in assets:
            metadata = asset.metadata_json
            if asset.id in keep_asset_ids:
                continue
            if metadata.get("listing_task_id") != str(listing_task_id):
                continue
            if metadata.get("source") not in sources:
                continue
            asset.status = "ARCHIVED"
            archived_count += 1
        return archived_count

    def list_assets(
        self,
        product_id: UUID,
        *,
        business_unit_id: str,
        include_archived: bool = False,
    ) -> list[EcommerceProductAsset]:
        product = self.session.get(EcommerceProduct, product_id)
        if product is None or product.business_unit_id != business_unit_id:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The requested product does not exist in this business unit.",
            )
        statement = select(EcommerceProductAsset).where(
            EcommerceProductAsset.product_id == product_id
        )
        if not include_archived:
            statement = statement.where(EcommerceProductAsset.status != "ARCHIVED")
        return list(
            self.session.scalars(
                statement.order_by(EcommerceProductAsset.created_at.desc())
            ).all()
        )

    def get_asset_record(self, asset_id: UUID) -> EcommerceProductAsset:
        asset = self.session.get(EcommerceProductAsset, asset_id)
        if asset is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Asset not found",
                detail="The requested asset does not exist.",
            )
        return asset

    def get_asset(
        self,
        asset_id: UUID,
    ) -> tuple[EcommerceProductAsset, bytes, ObjectStorage]:
        asset = self.get_asset_record(asset_id)
        storage = get_object_storage()
        try:
            data = storage.get_object(key=asset.object_key)
        except ObjectStorageError as exc:
            raise ApiProblem(
                status_code=503,
                code="OBJECT_STORAGE_UNAVAILABLE",
                title="Object storage is unavailable",
                detail="Unable to read the product asset.",
                retryable=True,
            ) from exc
        return asset, data, storage

    def create_listing_task(
        self,
        payload: EcommerceListingCreate,
        *,
        business_unit_id: str,
        correlation_id: str,
    ) -> EcommerceListingTask:
        product = self.session.get(EcommerceProduct, payload.product_id)
        if product is None or product.business_unit_id != business_unit_id:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The requested product does not exist in this business unit.",
            )
        profile = get_market_profile(payload.market_code)
        if profile is None:
            raise ApiProblem(
                status_code=422,
                code="UNSUPPORTED_MARKET",
                title="Unsupported target market",
                detail="Supported market codes are CN and US.",
            )
        if profile.code != "CN" and payload.sale_price is None:
            raise ApiProblem(
                status_code=422,
                code="MARKET_PRICE_REQUIRED",
                title="Local market price is required",
                detail="Provide sale_price in the target market currency.",
            )
        sale_price = (
            payload.sale_price
            if payload.sale_price is not None
            else product.price
        )
        rules = KnowledgeService(self.session).search(
            query=(
                "商品上架 标题 宣传 禁词 平台规则"
                if profile.code == "CN"
                else (
                    "Amazon US listing compliance, restricted claims, HS code, "
                    "country of origin and shipping requirements"
                )
            ),
            business_unit_id=business_unit_id,
            scope={
                "channel": payload.channel,
                "category": product.category,
                "audience": "ecommerce_operator",
                "market_code": profile.code,
                "locale": profile.locale,
            },
            top_k=5,
            correlation_id=correlation_id,
        )
        assets = list(
            self.session.scalars(
                select(EcommerceProductAsset)
                .where(
                    EcommerceProductAsset.product_id == product.id,
                    EcommerceProductAsset.status == "READY",
                )
                .order_by(EcommerceProductAsset.created_at)
            ).all()
        )
        image_assets = [asset for asset in assets if asset.asset_type == "IMAGE"]
        fallback_content = _generate_listing_content(product, profile, sale_price)
        try:
            generated_content = get_listing_content_generator().generate(
                product=product,
                profile=profile,
                sale_price=sale_price,
                rule_context=[
                    f"{hit.title} v{hit.version}: {hit.content}"
                    for hit in rules
                ],
                fallback_content=fallback_content,
            )
        except ContentGenerationError as exc:
            raise ApiProblem(
                status_code=502,
                code="LISTING_CONTENT_GENERATION_FAILED",
                title="Listing content generation failed",
                detail=str(exc)[:1500],
                retryable=True,
            ) from exc
        content = dict(generated_content.content)
        content["asset_ids"] = [str(asset.id) for asset in assets]
        primary_image = next(
            (
                asset
                for asset in image_assets
                if asset.metadata_json.get("is_primary") is True
            ),
            image_assets[0] if image_assets else None,
        )
        content["primary_image_asset_id"] = (
            str(primary_image.id) if primary_image else None
        )
        primary_visual_status = (
            str(primary_image.metadata_json.get("visual_audit_status", ""))
            if primary_image is not None
            else ""
        )
        primary_visual_issue = primary_visual_status in {"NEEDS_REVIEW", "ERROR"}
        triggers = _restricted_claims(product, content, profile.restricted_claims)
        market_missing = _market_readiness(product, profile)
        channel_missing = _channel_readiness(
            product,
            payload.channel,
            category_profile=self._category_profile_for_product(
                product, payload.channel
            ),
        )
        if not image_assets:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "MISSING_PRODUCT_IMAGE"
        elif primary_visual_issue:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "VISUAL_REVIEW_REQUIRED"
        elif not rules:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "COMPLIANCE_RULES_NOT_FOUND"
        elif market_missing:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = (
                "LOCALIZED_CONTENT_MISSING"
                if "localized_content" in market_missing
                else "CROSS_BORDER_DATA_MISSING"
            )
        elif channel_missing:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = (
                "PINDUODUO_ATTRIBUTES_MISSING"
                if payload.channel == "pinduoduo_sandbox"
                else "CHANNEL_ATTRIBUTES_MISSING"
            )
        elif triggers:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "RESTRICTED_CLAIM"
        else:
            status = "PENDING_REVIEW"
            risk_level = "R1"
            human_reason = None
        task = EcommerceListingTask(
            product_id=product.id,
            business_unit_id=business_unit_id,
            owner_employee_id=self._operation_employee_id(
                business_unit_id,
                "ecommerce_listing_operator",
            ),
            channel=payload.channel,
            market_code=profile.code,
            locale=profile.locale,
            currency=profile.currency,
            sale_price=sale_price,
            status=status,
            risk_level=risk_level,
            version=1,
            content_json=content,
            compliance_json={
                "restricted_claims": triggers,
                "rule_count": len(rules),
                "image_count": len(image_assets),
                "missing_product_image": not image_assets,
                "primary_image_visual_audit_status": primary_visual_status,
                "market_code": profile.code,
                "locale": profile.locale,
                "currency": profile.currency,
                "required_attributes_missing": market_missing,
                "channel_required_attributes_missing": channel_missing,
                "content_provider": generated_content.provider,
                "content_model": generated_content.model_name,
                "content_fallback_used": generated_content.fallback_used,
                "checked": True,
            },
            citations_json=[
                {
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "title": hit.title,
                    "version": hit.version,
                }
                for hit in rules
            ],
            generator_provider=generated_content.provider,
            generator_model=generated_content.model_name,
            human_reason=human_reason,
        )
        self.session.add(task)
        self.session.flush()
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.created",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_listing",
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="generate_listing",
            decision="EXECUTED",
            payload={
                "product_id": str(product.id),
                "sku": product.sku,
                "channel": task.channel,
                "market_code": task.market_code,
                "currency": task.currency,
                "status": task.status,
                "risk_level": task.risk_level,
                "citation_count": len(rules),
            },
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def list_tasks(
        self,
        *,
        business_unit_id: str,
        limit: int = 100,
    ) -> tuple[list[EcommerceListingListItem], int]:
        filters = [
            EcommerceListingTask.business_unit_id == business_unit_id
        ]
        total = self.session.scalar(
            select(func.count())
            .select_from(EcommerceListingTask)
            .where(*filters)
        ) or 0
        rows = self.session.execute(
            select(EcommerceListingTask, EcommerceProduct)
            .join(EcommerceProduct, EcommerceProduct.id == EcommerceListingTask.product_id)
            .where(*filters)
            .order_by(EcommerceListingTask.created_at.desc())
            .limit(limit)
        ).all()
        return [_list_item(task, product) for task, product in rows], total

    def get_listing_task(self, task_id: UUID) -> EcommerceListingTask:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        return task

    def detail(self, task_id: UUID) -> EcommerceListingDetail:
        row = self.session.execute(
            select(EcommerceListingTask, EcommerceProduct)
            .join(EcommerceProduct, EcommerceProduct.id == EcommerceListingTask.product_id)
            .where(EcommerceListingTask.id == task_id)
        ).one_or_none()
        if row is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        task, product = row
        return EcommerceListingDetail(
            **_list_item(task, product).model_dump(),
            business_unit_id=task.business_unit_id,
            product_category=product.category,
            content=task.content_json,
            compliance=task.compliance_json,
            citations=task.citations_json,
            generator_provider=task.generator_provider,
            generator_model=task.generator_model,
            error_message=task.error_message,
            reviewed_by=task.reviewed_by,
            reviewed_at=task.reviewed_at,
            published_at=task.published_at,
        )

    def create_listing_batch_job(
        self,
        payload: EcommerceListingBatchCreate,
        *,
        business_unit_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[EcommerceListingBatchJob, OutboxEvent]:
        if get_market_profile(payload.market_code) is None:
            raise ApiProblem(
                status_code=422,
                code="UNSUPPORTED_MARKET",
                title="Unsupported target market",
                detail="Supported market codes are CN and US.",
            )
        product_ids = list(dict.fromkeys(payload.product_ids))
        products = self.session.scalars(
            select(EcommerceProduct).where(
                EcommerceProduct.id.in_(product_ids),
                EcommerceProduct.business_unit_id == business_unit_id,
            )
        ).all()
        found_ids = {product.id for product in products}
        missing_ids = [
            str(product_id)
            for product_id in product_ids
            if product_id not in found_ids
        ]
        if missing_ids:
            raise ApiProblem(
                status_code=404,
                code="PRODUCTS_NOT_FOUND",
                title="One or more products do not exist",
                detail=", ".join(missing_ids),
            )
        job = EcommerceListingBatchJob(
            business_unit_id=business_unit_id,
            channel=payload.channel,
            market_code=payload.market_code,
            status="QUEUED",
            total_count=len(product_ids),
            succeeded_count=0,
            failed_count=0,
            correlation_id=correlation_id,
            created_by=actor_id,
        )
        self.session.add(job)
        self.session.flush()
        items = [
            EcommerceListingBatchItem(
                batch_job_id=job.id,
                product_id=product_id,
                status="QUEUED",
            )
            for product_id in product_ids
        ]
        self.session.add_all(items)
        event = OutboxEvent(
            aggregate_type="ecommerce_listing_batch_job",
            aggregate_id=job.id,
            event_type="ecommerce.listing.batch_generate",
            payload_json={
                "batch_job_id": str(job.id),
                "correlation_id": correlation_id,
            },
        )
        self.session.add(event)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.batch_job.queued",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_batch_job",
            resource_id=job.id,
            action="queue_listing_batch",
            decision="EXECUTED",
            payload={
                "total_count": len(product_ids),
                "channel": payload.channel,
                "market_code": payload.market_code,
            },
        )
        self.session.commit()
        self.session.refresh(job)
        self.session.refresh(event)
        return job, event

    def get_listing_batch_job(self, job_id: UUID) -> EcommerceListingBatchJob:
        job = self.session.get(EcommerceListingBatchJob, job_id)
        if job is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing batch job not found",
                detail="The requested listing batch job does not exist.",
            )
        return job

    def list_listing_batch_jobs(
        self,
        *,
        business_unit_id: str,
        limit: int = 20,
    ) -> EcommerceListingBatchJobListResponse:
        jobs = self.session.scalars(
            select(EcommerceListingBatchJob)
            .where(
                EcommerceListingBatchJob.business_unit_id
                == business_unit_id
            )
            .order_by(EcommerceListingBatchJob.created_at.desc())
            .limit(limit)
        ).all()
        total = self.session.scalar(
            select(func.count())
            .select_from(EcommerceListingBatchJob)
            .where(
                EcommerceListingBatchJob.business_unit_id
                == business_unit_id
            )
        ) or 0
        return EcommerceListingBatchJobListResponse(
            items=[self.listing_batch_view(job) for job in jobs],
            total=total,
        )

    def listing_batch_view(
        self,
        job: EcommerceListingBatchJob,
    ) -> EcommerceListingBatchJobView:
        items = self.session.scalars(
            select(EcommerceListingBatchItem)
            .where(EcommerceListingBatchItem.batch_job_id == job.id)
            .order_by(EcommerceListingBatchItem.created_at)
        ).all()
        return EcommerceListingBatchJobView(
            id=job.id,
            business_unit_id=job.business_unit_id,
            channel=job.channel,
            market_code=job.market_code,
            status=job.status,
            total_count=job.total_count,
            succeeded_count=job.succeeded_count,
            failed_count=job.failed_count,
            error_message=job.error_message,
            created_by=job.created_by,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            items=[
                EcommerceListingBatchItemView(
                    id=item.id,
                    product_id=item.product_id,
                    status=item.status,
                    listing_task_id=item.listing_task_id,
                    error_message=item.error_message,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                )
                for item in items
            ],
        )

    def update_listing_content(
        self,
        task_id: UUID,
        payload: EcommerceListingContentUpdate,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> EcommerceListingTask:
        task = self.session.scalar(
            select(EcommerceListingTask)
            .where(EcommerceListingTask.id == task_id)
            .with_for_update()
        )
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        if task.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="VERSION_CONFLICT",
                title="Listing task version conflict",
                detail="Reload the listing task before editing.",
            )
        if task.status not in {"PENDING_REVIEW", "NEEDS_HUMAN", "REJECTED"}:
            raise ApiProblem(
                status_code=409,
                code="INVALID_LISTING_STATE",
                title="Listing content cannot be edited",
                detail=f"Listing task is in {task.status} state.",
            )
        product = self.session.get(EcommerceProduct, task.product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The listing task product no longer exists.",
            )
        profile = get_market_profile(task.market_code)
        if profile is None:
            raise ApiProblem(
                status_code=409,
                code="UNSUPPORTED_MARKET",
                title="Unsupported target market",
                detail="The listing task has an unsupported market code.",
            )
        title = payload.title.strip()
        detail_description = payload.detail_description.strip()
        selling_points = [
            point.strip() for point in payload.selling_points if point.strip()
        ]
        if not title or not detail_description or not selling_points:
            raise ApiProblem(
                status_code=422,
                code="EMPTY_LISTING_CONTENT",
                title="Listing content is incomplete",
                detail="Title, description and at least one selling point are required.",
            )

        content = dict(task.content_json)
        content.update(
            {
                "title": title,
                "selling_points": selling_points,
                "detail_description": detail_description,
                "hashtags": list(
                    dict.fromkeys(tag.strip() for tag in payload.hashtags if tag.strip())
                ),
            }
        )
        has_image = (
            self.session.scalar(
                select(EcommerceProductAsset.id)
                .where(
                    EcommerceProductAsset.product_id == product.id,
                    EcommerceProductAsset.asset_type == "IMAGE",
                    EcommerceProductAsset.status == "READY",
                )
                .limit(1)
            )
            is not None
        )
        triggers = _restricted_claims(
            product,
            content,
            profile.restricted_claims,
        )
        market_missing = _market_readiness(product, profile)
        channel_missing = _channel_readiness(
            product,
            task.channel,
            category_profile=self._category_profile_for_product(
                product, task.channel
            ),
        )
        rule_count = int(task.compliance_json.get("rule_count", 0))
        if not has_image:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "MISSING_PRODUCT_IMAGE"
        elif rule_count == 0:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "COMPLIANCE_RULES_NOT_FOUND"
        elif market_missing:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = (
                "LOCALIZED_CONTENT_MISSING"
                if "localized_content" in market_missing
                else "CROSS_BORDER_DATA_MISSING"
            )
        elif channel_missing:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = (
                "PINDUODUO_ATTRIBUTES_MISSING"
                if task.channel == "pinduoduo_sandbox"
                else "CHANNEL_ATTRIBUTES_MISSING"
            )
        elif triggers:
            status = "NEEDS_HUMAN"
            risk_level = "R2"
            human_reason = "RESTRICTED_CLAIM"
        else:
            status = "PENDING_REVIEW"
            risk_level = "R1"
            human_reason = None

        task.content_json = content
        task.compliance_json = {
            **task.compliance_json,
            "restricted_claims": triggers,
            "missing_product_image": not has_image,
            "required_attributes_missing": market_missing,
            "channel_required_attributes_missing": channel_missing,
            "checked": True,
        }
        task.status = status
        task.risk_level = risk_level
        task.human_reason = human_reason
        task.reviewed_by = None
        task.reviewed_at = None
        task.version += 1
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.content_updated",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="edit_listing_content",
            decision=status,
            payload={
                "version": task.version,
                "title": title,
                "selling_point_count": len(selling_points),
                "restricted_claims": triggers,
            },
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def export_listing_package(
        self,
        task_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[bytes, str]:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        product = self.session.get(EcommerceProduct, task.product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The listing task product no longer exists.",
            )
        product_assets = self.list_assets(
            product.id,
            business_unit_id=product.business_unit_id,
        )
        primary_image_id = str(
            task.content_json.get("primary_image_asset_id", "")
        )
        assets = [
            asset
            for asset in product_assets
            if (
                asset.asset_type == "IMAGE"
                and (
                    str(asset.id) == primary_image_id
                    or asset.metadata_json.get("listing_task_id") == str(task.id)
                )
            )
            or (
                asset.asset_type in {"VIDEO", "SUBTITLE", "AUDIO"}
                and asset.metadata_json.get("listing_task_id") == str(task.id)
            )
        ]
        if not any(
            asset.asset_type == "IMAGE"
            and asset.metadata_json.get("source") != "STORYBOARD_GENERATED"
            for asset in assets
        ):
            image_candidates = [
                asset
                for asset in product_assets
                if asset.asset_type == "IMAGE"
                and asset.metadata_json.get("source") != "STORYBOARD_GENERATED"
            ]
            fallback_image = next(
                (
                    asset
                    for asset in image_candidates
                    if asset.metadata_json.get("source") != "AI_GENERATED"
                ),
                image_candidates[0] if image_candidates else None,
            )
            if fallback_image is not None:
                assets.append(fallback_image)
        storage = get_object_storage()
        asset_manifest: list[dict[str, object]] = []
        files: list[tuple[str, bytes]] = []
        for asset in assets:
            folder = {
                "IMAGE": "images",
                "VIDEO": "video",
                "SUBTITLE": "subtitles",
                "AUDIO": "audio",
            }.get(asset.asset_type, "assets")
            safe_name = _safe_export_filename(asset.filename)
            archive_name = (
                f"assets/{folder}/{asset.id.hex[:8]}-{safe_name}"
            )
            try:
                content = storage.get_object(key=asset.object_key)
            except ObjectStorageError as exc:
                raise ApiProblem(
                    status_code=503,
                    code="OBJECT_STORAGE_UNAVAILABLE",
                    title="Listing package export failed",
                    detail="A listing asset could not be read from object storage.",
                    retryable=True,
                ) from exc
            files.append((archive_name, content))
            asset_manifest.append(
                {
                    "id": str(asset.id),
                    "type": asset.asset_type,
                    "path": archive_name,
                    "content_type": asset.content_type,
                    "size_bytes": asset.size_bytes,
                    "metadata": asset.metadata_json,
                }
            )
        manifest = {
            "schema_version": "1.0",
            "task": {
                "id": str(task.id),
                "status": task.status,
                "version": task.version,
                "channel": task.channel,
                "market_code": task.market_code,
                "locale": task.locale,
                "currency": task.currency,
                "sale_price": task.sale_price,
                "risk_level": task.risk_level,
                "human_reason": task.human_reason,
                "reviewed_by": task.reviewed_by,
                "reviewed_at": (
                    task.reviewed_at.isoformat() if task.reviewed_at else None
                ),
                "published_at": (
                    task.published_at.isoformat() if task.published_at else None
                ),
            },
            "product": {
                "id": str(product.id),
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "brand": product.brand,
                "base_price": product.price,
                "attributes": product.attributes_json,
            },
            "content": task.content_json,
            "compliance": task.compliance_json,
            "citations": task.citations_json,
            "assets": asset_manifest,
            "generated_by": "UniEmployee Ecommerce",
            "generated_at": datetime.now(UTC).isoformat(),
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(
                "listing.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            archive.writestr(
                "README.txt",
                (
                    "电商上架资料包\n"
                    f"SKU: {product.sku}\n"
                    f"市场: {task.market_code} / {task.locale}\n"
                    f"售价: {task.currency} {task.sale_price:.2f}\n"
                    "请先完成人工审核，再上传到实际电商平台。\n"
                ),
            )
            for name, content in files:
                archive.writestr(name, content)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.package_exported",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="export_listing_package",
            decision="EXECUTED",
            payload={
                "asset_count": len(files),
                "task_version": task.version,
            },
        )
        self.session.commit()
        filename = (
            f"listing-{_safe_export_filename(product.sku).lower()}-"
            f"{task.id.hex[:8]}.zip"
        )
        return buffer.getvalue(), filename

    def review(
        self,
        task_id: UUID,
        payload: EcommerceListingReview,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[EcommerceListingTask, OutboxEvent | None]:
        task = self.session.scalar(
            select(EcommerceListingTask)
            .where(EcommerceListingTask.id == task_id)
            .with_for_update()
        )
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        if task.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="VERSION_CONFLICT",
                title="Listing task version conflict",
                detail="Reload the listing task before reviewing.",
            )
        if task.status not in {"PENDING_REVIEW", "NEEDS_HUMAN"}:
            raise ApiProblem(
                status_code=409,
                code="INVALID_LISTING_STATE",
                title="Listing task cannot be reviewed",
                detail=f"Listing task is in {task.status} state.",
            )
        now = datetime.now(UTC)
        task.reviewed_by = actor_id
        task.reviewed_at = now
        task.version += 1
        outbox_event = None
        if payload.decision == "ACCEPTED":
            task.status = "PUBLISHING"
            task.human_reason = None
            outbox_event = OutboxEvent(
                aggregate_type="ecommerce_listing_task",
                aggregate_id=task.id,
                event_type="ecommerce.listing.publish",
                payload_json={
                    "task_id": str(task.id),
                    "correlation_id": correlation_id,
                },
            )
            self.session.add(outbox_event)
        elif payload.decision == "REJECTED":
            task.status = "REJECTED"
            task.human_reason = payload.reason_code
        else:
            raise ApiProblem(
                status_code=422,
                code="SCHEMA_VALIDATION_FAILED",
                title="Invalid review decision",
                detail="decision must be ACCEPTED or REJECTED.",
            )
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.reviewed",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="review_listing",
            decision=payload.decision,
            reason_code=payload.reason_code,
        )
        self.session.commit()
        self.session.refresh(task)
        return task, outbox_event

    def publish(self, task_id: UUID, correlation_id: str) -> EcommerceListingTask:
        task = self.session.scalar(
            select(EcommerceListingTask)
            .where(EcommerceListingTask.id == task_id)
            .with_for_update()
        )
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        if task.status == "PUBLISHED":
            return task
        if task.status != "PUBLISHING":
            return task
        product = self.session.get(EcommerceProduct, task.product_id)
        if product is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Product not found",
                detail="The listing task product no longer exists.",
            )
        adapter = get_ecommerce_channel_adapter()
        try:
            result = adapter.publish(
                EcommerceListingPayload(
                    task_id=task.id,
                    sku=product.sku,
                    channel=task.channel,
                    product_name=product.name,
                    category=product.category,
                    price=product.price,
                    attributes=product.attributes_json,
                    content=task.content_json,
                    asset_ids=[
                        str(asset_id)
                        for asset_id in task.content_json.get("asset_ids", [])
                        if isinstance(asset_id, str)
                    ],
                )
            )
        except EcommerceChannelError as exc:
            task.error_message = str(exc)[:2000]
            self.session.commit()
            raise
        task.status = "PUBLISHED"
        task.external_listing_id = result.external_listing_id
        task.error_message = None
        task.published_at = datetime.now(UTC)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.published",
            actor_type="SERVICE",
            actor_id="digital_employee.ecommerce_listing",
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="publish_listing",
            decision="EXECUTED",
            payload={"external_listing_id": task.external_listing_id},
        )
        self.session.commit()
        self.session.refresh(task)
        return task

    def fail_publish(self, task_id: UUID, error: Exception) -> None:
        task = self.session.get(EcommerceListingTask, task_id)
        if task is None:
            return
        task.status = "FAILED"
        task.error_message = str(error)[:2000]
        self.session.commit()

    def set_primary_asset(self, asset_id: UUID) -> EcommerceProductAsset:
        asset = self.session.get(EcommerceProductAsset, asset_id)
        if asset is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Asset not found",
                detail="The requested asset does not exist.",
            )
        if asset.asset_type != "IMAGE" or asset.status != "READY":
            raise ApiProblem(
                status_code=409,
                code="INVALID_PRIMARY_ASSET",
                title="Asset cannot be used as primary image",
                detail="Only READY image assets can be selected as the primary image.",
            )
        siblings = self.session.scalars(
            select(EcommerceProductAsset).where(
                EcommerceProductAsset.product_id == asset.product_id
            )
        ).all()
        for sibling in siblings:
            metadata = dict(sibling.metadata_json)
            metadata["is_primary"] = sibling.id == asset.id
            sibling.metadata_json = metadata
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def archive_asset(
        self,
        asset_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> EcommerceProductAsset:
        asset = self.session.get(EcommerceProductAsset, asset_id)
        if asset is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Asset not found",
                detail="The requested asset does not exist.",
            )
        metadata = dict(asset.metadata_json)
        metadata["is_primary"] = False
        asset.metadata_json = metadata
        asset.status = "ARCHIVED"
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.asset.archived",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_product",
            resource_id=asset.product_id,
            action="archive_asset",
            decision="EXECUTED",
            payload={"asset_id": str(asset.id)},
        )
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def accept_visual_review(
        self,
        asset_id: UUID,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> EcommerceProductAsset:
        asset = self.session.get(EcommerceProductAsset, asset_id)
        if asset is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Asset not found",
                detail="The requested product asset does not exist.",
            )
        if asset.asset_type != "IMAGE":
            raise ApiProblem(
                status_code=409,
                code="INVALID_VISUAL_REVIEW_ASSET",
                title="Asset cannot receive visual review",
                detail="Only image assets support visual review.",
            )
        metadata = dict(asset.metadata_json)
        metadata.update(
            {
                "visual_audit_status": "ACCEPTED",
                "visual_reviewed_by": actor_id,
                "visual_reviewed_at": datetime.now(UTC).isoformat(),
            }
        )
        asset.metadata_json = metadata
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.asset.visual_review_accepted",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_product",
            resource_id=asset.product_id,
            action="accept_visual_review",
            decision="ACCEPTED",
            payload={"asset_id": str(asset.id)},
        )
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def retry_publish(
        self,
        task_id: UUID,
        payload: EcommerceListingRetryRequest,
        *,
        actor_id: str,
        correlation_id: str,
    ) -> tuple[EcommerceListingTask, OutboxEvent]:
        task = self.session.scalar(
            select(EcommerceListingTask)
            .where(EcommerceListingTask.id == task_id)
            .with_for_update()
        )
        if task is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Listing task not found",
                detail="The requested listing task does not exist.",
            )
        if task.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="VERSION_CONFLICT",
                title="Listing task version conflict",
                detail="Reload the listing task before retrying.",
            )
        if task.status != "FAILED":
            raise ApiProblem(
                status_code=409,
                code="INVALID_LISTING_STATE",
                title="Listing task cannot be retried",
                detail=f"Listing task is in {task.status} state.",
            )
        task.status = "PUBLISHING"
        task.error_message = None
        task.version += 1
        event = OutboxEvent(
            aggregate_type="ecommerce_listing_task",
            aggregate_id=task.id,
            event_type="ecommerce.listing.publish",
            payload_json={
                "task_id": str(task.id),
                "correlation_id": correlation_id,
            },
        )
        self.session.add(event)
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="ecommerce.listing.retry_requested",
            actor_type="USER",
            actor_id=actor_id,
            resource_type="ecommerce_listing_task",
            resource_id=task.id,
            action="retry_publish",
            decision="EXECUTED",
            reason_code=payload.reason_code,
        )
        self.session.commit()
        self.session.refresh(task)
        return task, event

    @staticmethod
    def product_view(product: EcommerceProduct) -> EcommerceProductView:
        return EcommerceProductView(
            id=product.id,
            business_unit_id=product.business_unit_id,
            sku=product.sku,
            name=product.name,
            category=product.category,
            brand=product.brand,
            price=product.price,
            attributes=product.attributes_json,
            status=product.status,
            created_by=product.created_by,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )

    @staticmethod
    def asset_view(asset: EcommerceProductAsset) -> EcommerceProductAssetView:
        return EcommerceProductAssetView(
            id=asset.id,
            product_id=asset.product_id,
            business_unit_id=asset.business_unit_id,
            owner_employee_id=asset.owner_employee_id,
            asset_type=asset.asset_type,
            filename=asset.filename,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            status=asset.status,
            metadata=asset.metadata_json,
            created_by=asset.created_by,
            created_at=asset.created_at,
        )

    def _operation_employee_id(
        self,
        business_unit_id: str,
        template_code: str,
    ) -> UUID | None:
        return self.session.scalar(
            select(DigitalEmployee.id)
            .where(
                DigitalEmployee.business_unit_id == business_unit_id,
                DigitalEmployee.template_code == template_code,
                DigitalEmployee.status == "ACTIVE",
            )
            .order_by(DigitalEmployee.created_at)
            .limit(1)
        )


def _generate_listing_content(
    product: EcommerceProduct,
    profile: MarketProfile,
    sale_price: float,
) -> dict[str, Any]:
    localized = _localized_product_data(product, profile)
    if profile.code == "CN":
        brand = f"{product.brand} " if product.brand else ""
    else:
        localized_brand = (
            str(localized.get("brand", "")).strip()
            if localized is not None
            else ""
        )
        if not localized_brand and product.brand and product.brand.isascii():
            localized_brand = product.brand
        brand = f"{localized_brand} " if localized_brand else ""
    product_name = (
        str(localized.get("name", product.name))
        if localized is not None
        else product.name
    )
    category = (
        str(localized.get("category", product.category))
        if localized is not None
        else product.category
    )
    localized_points = (
        [
            str(point)
            for point in localized.get("selling_points", [])
            if str(point).strip()
        ]
        if localized is not None
        and isinstance(localized.get("selling_points"), list)
        else []
    )
    if profile.code != "CN":
        attributes = ", ".join(
            f"{key}: {value}"
            for key, value in product.attributes_json.items()
            if key
            not in {
                "localizations",
                "hs_code",
                "origin_country",
                "weight_kg",
                "package_dimensions_cm",
            }
            and isinstance(value, (str, int, float))
        )
        bullets = localized_points[:3]
        if len(bullets) < 3:
            bullets.extend(
                [
                    f"Designed for everyday {category.lower()} use.",
                    (
                        f"Product details: {attributes}."
                        if attributes
                        else "Clear product details and straightforward use."
                    ),
                ][: 3 - len(bullets)]
            )
        bullets.append(
            f"List price ${sale_price:.2f}; final price and offers are shown "
            "on the marketplace listing."
        )
        return {
            "market_code": profile.code,
            "locale": profile.locale,
            "title": f"{brand}{product_name} | {category}"[:200],
            "selling_points": bullets[:5],
            "detail_description": (
                f"{brand}{product_name} is designed for {category} use. "
                f"{attributes + '. ' if attributes else ''}"
                "Review the marketplace listing for final product details, "
                "shipping information and the applicable price."
            ),
            "short_video_script": [
                {
                    "second": "0-3",
                    "visual": "Product hero shot",
                    "line": "Meet the product",
                },
                {
                    "second": "3-8",
                    "visual": "Product in use",
                    "line": bullets[0],
                },
                {
                    "second": "8-15",
                    "visual": "Feature and price card",
                    "line": "View details and current price",
                },
            ],
            "hashtags": [
                category,
                product_name[:30],
                "AmazonFinds",
            ],
        }
    attributes = "，".join(
        f"{key}：{value}"
        for key, value in product.attributes_json.items()
        if key not in {"localizations", "package_dimensions_cm"}
        and isinstance(value, (str, int, float))
    )
    bullets = [
        f"{brand}{product.name}，适合{product.category}场景",
        f"核心信息：{attributes}" if attributes else "核心信息清晰，使用方式简单",
        f"售价 ¥{product.price:.2f}，具体优惠以店铺页面为准",
    ]
    return {
        "market_code": profile.code,
        "locale": profile.locale,
        "title": f"{brand}{product.name}｜{product.category}"[:60],
        "selling_points": bullets,
        "detail_description": (
            f"{brand}{product.name} 是一款面向{product.category}场景的商品。"
            f"{attributes}。商品信息请以页面展示和实际收到为准。"
        ),
        "short_video_script": [
            {"second": "0-3", "visual": "商品正面特写", "line": "先看关键卖点"},
            {"second": "3-8", "visual": "使用场景演示", "line": bullets[0]},
            {"second": "8-15", "visual": "细节与价格卡片", "line": "点击查看详情"},
        ],
        "hashtags": [product.category, product.name[:20], "好物推荐"],
    }


def _restricted_claims(
    product: EcommerceProduct,
    content: dict[str, Any],
    restricted_claims: tuple[str, ...],
) -> list[str]:
    searchable = " ".join(
        [
            product.name,
            product.category,
            str(product.attributes_json),
            str(content),
        ]
    )
    lowered = searchable.lower()
    return [
        claim
        for claim in restricted_claims
        if claim.lower() in lowered
    ]


def _localized_product_data(
    product: EcommerceProduct,
    profile: MarketProfile,
) -> dict[str, Any] | None:
    localizations = product.attributes_json.get("localizations")
    if not isinstance(localizations, dict):
        return None
    localized = localizations.get(profile.locale)
    return localized if isinstance(localized, dict) else None


def _market_readiness(
    product: EcommerceProduct,
    profile: MarketProfile,
) -> list[str]:
    if profile.code == "CN":
        return []
    missing: list[str] = []
    localized = _localized_product_data(product, profile)
    localized_points = localized.get("selling_points") if localized else None
    if (
        localized is None
        or not str(localized.get("name", "")).strip()
        or not str(localized.get("category", "")).strip()
        or not isinstance(localized_points, list)
        or not localized_points
    ):
        missing.append("localized_content")
    hs_code = str(product.attributes_json.get("hs_code", "")).replace(" ", "")
    if not (hs_code.isdigit() and 6 <= len(hs_code) <= 10):
        missing.append("hs_code")
    origin_country = str(
        product.attributes_json.get("origin_country", "")
    ).strip()
    if len(origin_country) != 2 or not origin_country.isalpha():
        missing.append("origin_country")
    weight = product.attributes_json.get("weight_kg")
    if not isinstance(weight, (int, float)) or float(weight) <= 0:
        missing.append("weight_kg")
    dimensions = product.attributes_json.get("package_dimensions_cm")
    if not isinstance(dimensions, dict) or any(
        not isinstance(dimensions.get(axis), (int, float))
        or float(dimensions[axis]) <= 0
        for axis in ("length", "width", "height")
    ):
        missing.append("package_dimensions_cm")
    return missing


def _channel_readiness(
    product: EcommerceProduct,
    channel: str,
    *,
    category_profile: EcommerceCategoryProfile | None = None,
) -> list[str]:
    if category_profile is not None:
        missing = [
            key
            for key in category_profile.required_attributes_json
            if not _attribute_present(product.attributes_json.get(key))
        ]
        if not product.brand:
            missing.insert(0, "brand")
        return missing
    if (
        channel != "pinduoduo_sandbox"
        or "雪地靴" not in f"{product.name}{product.category}"
    ):
        return []
    required_attributes = (
        "color",
        "size_range",
        "upper_material",
        "lining_material",
        "sole_material",
        "heel_height_cm",
        "shaft_height_cm",
        "closure",
        "gender",
        "season",
        "stock",
    )
    missing = [
        key
        for key in required_attributes
        if not _attribute_present(product.attributes_json.get(key))
    ]
    if not product.brand:
        missing.insert(0, "brand")
    return missing


def _attribute_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _list_item(
    task: EcommerceListingTask,
    product: EcommerceProduct,
) -> EcommerceListingListItem:
    return EcommerceListingListItem(
        id=task.id,
        product_id=product.id,
        sku=product.sku,
        product_name=product.name,
        channel=task.channel,
        market_code=task.market_code,
        owner_employee_id=task.owner_employee_id,
        locale=task.locale,
        currency=task.currency,
        sale_price=task.sale_price,
        status=task.status,
        risk_level=task.risk_level,
        version=task.version,
        human_reason=task.human_reason,
        external_listing_id=task.external_listing_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _duration_seconds(
    started_at: datetime | None,
    completed_at: datetime | None,
) -> float | None:
    if started_at is None or completed_at is None:
        return None
    seconds = (completed_at - started_at).total_seconds()
    return max(0.0, seconds)


def _safe_export_filename(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return (normalized or "asset")[:120]


def _asset_type(content_type: str) -> str | None:
    normalized = content_type.lower().split(";", 1)[0].strip()
    if normalized in {"image/jpeg", "image/png", "image/webp"}:
        return "IMAGE"
    if normalized in {"video/mp4", "video/webm", "video/quicktime"}:
        return "VIDEO"
    if normalized == "text/vtt":
        return "SUBTITLE"
    if normalized in {
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
    }:
        return "AUDIO"
    return None


def _scene_duration(value: str) -> float:
    try:
        start_text, end_text = value.split("-", 1)
        duration = float(end_text) - float(start_text)
    except (ValueError, TypeError):
        return 3.0
    return min(max(duration, 1.0), 15.0)
