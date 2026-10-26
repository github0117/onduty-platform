from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
    status,
)

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.ecommerce.models import (
    EcommerceCategoryProfile,
    EcommerceListingBatchJob,
    EcommerceListingTask,
    EcommerceProduct,
    EcommerceProductAsset,
    EcommerceVideoRenderJob,
)
from ticket_agent.ecommerce.pinduoduo_gateway import (
    PinduoduoGatewayError,
    get_pinduoduo_gateway,
)
from ticket_agent.ecommerce.product_import import (
    ProductImportParseError,
    category_product_import_template,
    product_import_template,
)
from ticket_agent.ecommerce.schemas import (
    ChannelConnectionTestResult,
    EcommerceCategoryProfileCreate,
    EcommerceCategoryProfileUpdate,
    EcommerceCategoryProfileView,
    EcommerceImageBatchGenerateRequest,
    EcommerceImageBatchGenerateResponse,
    EcommerceImageGenerateRequest,
    EcommerceImageGenerationListResponse,
    EcommerceListingBatchCreate,
    EcommerceListingBatchJobListResponse,
    EcommerceListingBatchJobView,
    EcommerceListingContentUpdate,
    EcommerceListingCreate,
    EcommerceListingDetail,
    EcommerceListingListResponse,
    EcommerceListingMutation,
    EcommerceListingRetryRequest,
    EcommerceListingReview,
    EcommerceOperationalMetrics,
    EcommerceProductAssetView,
    EcommerceProductCreate,
    EcommerceProductImportPreview,
    EcommerceProductImportResult,
    EcommerceProductView,
    EcommerceVideoRenderJobCreate,
    EcommerceVideoRenderJobListResponse,
    EcommerceVideoRenderJobView,
)
from ticket_agent.ecommerce.service import EcommerceService
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_ticket_writer,
    resolve_business_unit,
)
from ticket_agent.outbox.service import dispatch_outbox_event
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.rate_limit import rate_limited

router = APIRouter()


def _category_for_access(
    service: EcommerceService,
    profile_id: UUID,
    principal: Actor,
) -> EcommerceCategoryProfile:
    profile = service.get_category_profile(profile_id)
    ensure_business_unit_access(principal, profile.business_unit_id)
    return profile


def _product_for_access(
    service: EcommerceService,
    product_id: UUID,
    principal: Actor,
) -> EcommerceProduct:
    product = service.get_product(product_id)
    ensure_business_unit_access(principal, product.business_unit_id)
    return product


def _asset_for_access(
    service: EcommerceService,
    asset_id: UUID,
    principal: Actor,
) -> EcommerceProductAsset:
    asset = service.get_asset_record(asset_id)
    ensure_business_unit_access(principal, asset.business_unit_id)
    return asset


def _listing_task_for_access(
    service: EcommerceService,
    task_id: UUID,
    principal: Actor,
) -> EcommerceListingTask:
    task = service.get_listing_task(task_id)
    ensure_business_unit_access(principal, task.business_unit_id)
    return task


def _listing_batch_job_for_access(
    service: EcommerceService,
    job_id: UUID,
    principal: Actor,
) -> EcommerceListingBatchJob:
    job = service.get_listing_batch_job(job_id)
    ensure_business_unit_access(principal, job.business_unit_id)
    return job


def _video_render_job_for_access(
    service: EcommerceService,
    job_id: UUID,
    principal: Actor,
) -> EcommerceVideoRenderJob:
    job = service.get_video_render_job(job_id)
    ensure_business_unit_access(principal, job.business_unit_id)
    return job


@router.post(
    "/ecommerce/categories",
    response_model=EcommerceCategoryProfileView,
    status_code=status.HTTP_201_CREATED,
)
def create_ecommerce_category(
    payload: EcommerceCategoryProfileCreate,
    db: DbSession,
    principal: Actor,
) -> EcommerceCategoryProfileView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = EcommerceService(db)
    return service.category_profile_view(
        service.create_category_profile(payload, actor_id=principal.actor_id)
    )


@router.get(
    "/ecommerce/categories",
    response_model=list[EcommerceCategoryProfileView],
)
def list_ecommerce_categories(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[EcommerceCategoryProfileView]:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = EcommerceService(db)
    return [
        service.category_profile_view(profile)
        for profile in service.list_category_profiles(business_unit_id)
    ]


@router.patch(
    "/ecommerce/categories/{profile_id}",
    response_model=EcommerceCategoryProfileView,
)
def update_ecommerce_category(
    profile_id: UUID,
    payload: EcommerceCategoryProfileUpdate,
    db: DbSession,
    principal: Actor,
) -> EcommerceCategoryProfileView:
    ensure_knowledge_admin(principal)
    service = EcommerceService(db)
    _category_for_access(service, profile_id, principal)
    return service.category_profile_view(
        service.update_category_profile(profile_id, payload)
    )


@router.post(
    "/ecommerce/channels/pinduoduo/test",
    response_model=ChannelConnectionTestResult,
)
def test_pinduoduo_connection(principal: Actor) -> ChannelConnectionTestResult:
    ensure_ticket_writer(principal)
    gateway = get_pinduoduo_gateway()
    if not gateway.configured:
        return ChannelConnectionTestResult(
            configured=False,
            success=False,
            message=(
                "Pinduoduo application client_id and client_secret "
                "are not configured"
            ),
        )
    try:
        result = gateway.test_connection()
    except PinduoduoGatewayError as exc:
        return ChannelConnectionTestResult(
            configured=True,
            success=False,
            message=str(exc)[:1000],
        )
    return ChannelConnectionTestResult(
        configured=True,
        success=True,
        message=(
            "Pinduoduo gateway connection succeeded; merchant "
            "authorization is ready"
            if gateway.merchant_authorized
            else (
                "Pinduoduo gateway connection succeeded; "
                "merchant store authorization is still missing"
            )
        ),
        response=result.payload,
    )


@router.get("/ecommerce/metrics", response_model=EcommerceOperationalMetrics)
def get_ecommerce_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> EcommerceOperationalMetrics:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return EcommerceService(db).operational_metrics(business_unit_id)


@router.post("/ecommerce/operations/backfill-employee-owners")
def backfill_ecommerce_employee_owners(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> dict[str, int]:
    ensure_knowledge_admin(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return EcommerceService(db).backfill_operation_owners(business_unit_id)


@router.get(
    "/ecommerce/image-generations",
    response_model=EcommerceImageGenerationListResponse,
)
def list_image_generations(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> EcommerceImageGenerationListResponse:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return EcommerceService(db).list_image_generations(
        business_unit_id=business_unit_id,
        limit=limit,
    )


@router.post(
    "/ecommerce/products",
    response_model=EcommerceProductView,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: EcommerceProductCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    product = EcommerceService(db).create_product(
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return EcommerceService.product_view(product)


@router.get("/ecommerce/products", response_model=list[EcommerceProductView])
def list_products(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> list[EcommerceProductView]:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = EcommerceService(db)
    return [
        service.product_view(product)
        for product in service.list_products(business_unit_id)
    ]


@router.get("/ecommerce/products/import-template")
def download_product_import_template(principal: Actor) -> Response:
    ensure_ticket_writer(principal)
    return Response(
        content=product_import_template(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="pinduoduo-snow-boots-products.csv"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/ecommerce/categories/{profile_id}/import-template")
def download_category_import_template(
    profile_id: UUID,
    db: DbSession,
    principal: Actor,
) -> Response:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    profile = _category_for_access(service, profile_id, principal)
    return Response(
        content=category_product_import_template(
            category_name=profile.name,
            required_attributes=profile.required_attributes_json,
        ),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{profile.code}-products.csv"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/ecommerce/products/import/preview",
    response_model=EcommerceProductImportPreview,
)
async def preview_product_import(
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    category_profile_id: Annotated[UUID | None, Query()] = None,
) -> EcommerceProductImportPreview:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    if category_profile_id is not None:
        _category_for_access(
            EcommerceService(db), category_profile_id, principal
        )
    try:
        return EcommerceService(db).preview_product_import(
            await request.body(),
            business_unit_id=business_unit_id,
            category_profile_id=category_profile_id,
        )
    except ProductImportParseError as exc:
        raise ApiProblem(
            status_code=422,
            code="PRODUCT_IMPORT_INVALID",
            title="Product CSV is invalid",
            detail=str(exc),
        ) from exc


@router.post(
    "/ecommerce/products/import",
    response_model=EcommerceProductImportResult,
)
async def import_products(
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    category_profile_id: Annotated[UUID | None, Query()] = None,
) -> EcommerceProductImportResult:
    ensure_knowledge_admin(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    if category_profile_id is not None:
        _category_for_access(
            EcommerceService(db), category_profile_id, principal
        )
    try:
        return EcommerceService(db).import_products(
            await request.body(),
            business_unit_id=business_unit_id,
            actor_id=principal.actor_id,
            correlation_id=correlation_id(request),
            category_profile_id=category_profile_id,
        )
    except ProductImportParseError as exc:
        raise ApiProblem(
            status_code=422,
            code="PRODUCT_IMPORT_INVALID",
            title="Product CSV is invalid",
            detail=str(exc),
        ) from exc


@router.post(
    "/ecommerce/products/{product_id}/assets",
    response_model=EcommerceProductAssetView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_asset(
    product_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
    filename: Annotated[str, Query(min_length=1, max_length=255)],
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _product_for_access(service, product_id, principal)
    data = await request.body()
    content_type = request.headers.get(
        "content-type",
        "application/octet-stream",
    )
    upload_metadata: dict[str, object] = {"source": "USER_UPLOAD"}
    if content_type.startswith("audio/"):
        upload_metadata["asset_role"] = "BACKGROUND_MUSIC"
    asset = service.create_asset(
        product_id,
        filename=filename,
        content_type=content_type,
        data=data,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
        extra_metadata=upload_metadata,
    )
    return service.asset_view(asset)


@router.post(
    "/ecommerce/products/{product_id}/assets/generate",
    response_model=EcommerceProductAssetView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited())],
)
def generate_product_image(
    product_id: UUID,
    payload: EcommerceImageGenerateRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _product_for_access(service, product_id, principal)
    asset = service.generate_product_image(
        product_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.asset_view(asset)


@router.post(
    "/ecommerce/products/{product_id}/assets/generate-batch",
    response_model=EcommerceImageBatchGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited())],
)
def generate_product_image_candidates(
    product_id: UUID,
    payload: EcommerceImageBatchGenerateRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceImageBatchGenerateResponse:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _product_for_access(service, product_id, principal)
    assets = service.generate_product_images(
        product_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return EcommerceImageBatchGenerateResponse(
        items=[service.asset_view(asset) for asset in assets]
    )


@router.get(
    "/ecommerce/products/{product_id}/assets",
    response_model=list[EcommerceProductAssetView],
)
def list_product_assets(
    product_id: UUID,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> list[EcommerceProductAssetView]:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = EcommerceService(db)
    _product_for_access(service, product_id, principal)
    return [
        service.asset_view(asset)
        for asset in service.list_assets(
            product_id,
            business_unit_id=business_unit_id,
            include_archived=include_archived,
        )
    ]


@router.get("/ecommerce/assets/{asset_id}/content")
def get_product_asset_content(
    asset_id: UUID,
    db: DbSession,
    principal: Actor,
) -> Response:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _asset_for_access(service, asset_id, principal)
    asset, data, _storage = service.get_asset(asset_id)
    return Response(
        content=data,
        media_type=asset.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{asset.filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


@router.post(
    "/ecommerce/assets/{asset_id}/primary",
    response_model=EcommerceProductAssetView,
)
def set_primary_product_asset(
    asset_id: UUID,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _asset_for_access(service, asset_id, principal)
    return service.asset_view(service.set_primary_asset(asset_id))


@router.post(
    "/ecommerce/assets/{asset_id}/archive",
    response_model=EcommerceProductAssetView,
)
def archive_product_asset(
    asset_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _asset_for_access(service, asset_id, principal)
    asset = service.archive_asset(
        asset_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.asset_view(asset)


@router.post(
    "/ecommerce/assets/{asset_id}/visual-review/accept",
    response_model=EcommerceProductAssetView,
)
def accept_product_asset_visual_review(
    asset_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _asset_for_access(service, asset_id, principal)
    asset = service.accept_visual_review(
        asset_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.asset_view(asset)


@router.post(
    "/ecommerce/listing-tasks",
    response_model=EcommerceListingDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_listing_task(
    payload: EcommerceListingCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> EcommerceListingDetail:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = EcommerceService(db)
    _product_for_access(service, payload.product_id, principal)
    task = service.create_listing_task(
        payload,
        business_unit_id=business_unit_id,
        correlation_id=correlation_id(request),
    )
    return service.detail(task.id)


@router.post(
    "/ecommerce/listing-batch-jobs",
    response_model=EcommerceListingBatchJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_listing_batch_job(
    payload: EcommerceListingBatchCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> EcommerceListingBatchJobView:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    for product_id in set(payload.product_ids):
        product = db.get(EcommerceProduct, product_id)
        if product is not None:
            ensure_business_unit_access(principal, product.business_unit_id)
    service = EcommerceService(db)
    job, event = service.create_listing_batch_job(
        payload,
        business_unit_id=business_unit_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    background_tasks.add_task(dispatch_outbox_event, event.id)
    return service.listing_batch_view(job)


@router.get(
    "/ecommerce/listing-batch-jobs",
    response_model=EcommerceListingBatchJobListResponse,
)
def list_listing_batch_jobs(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EcommerceListingBatchJobListResponse:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return EcommerceService(db).list_listing_batch_jobs(
        business_unit_id=business_unit_id,
        limit=limit,
    )


@router.get(
    "/ecommerce/listing-batch-jobs/{job_id}",
    response_model=EcommerceListingBatchJobView,
)
def get_listing_batch_job(
    job_id: UUID,
    db: DbSession,
    principal: Actor,
) -> EcommerceListingBatchJobView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    return service.listing_batch_view(
        _listing_batch_job_for_access(service, job_id, principal)
    )


@router.get("/ecommerce/listing-tasks", response_model=EcommerceListingListResponse)
def list_listing_tasks(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> EcommerceListingListResponse:
    ensure_ticket_writer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    items, total = EcommerceService(db).list_tasks(
        business_unit_id=business_unit_id,
        limit=limit,
    )
    return EcommerceListingListResponse(items=items, total=total)


@router.get(
    "/ecommerce/listing-tasks/{task_id}",
    response_model=EcommerceListingDetail,
)
def get_listing_task(
    task_id: UUID,
    db: DbSession,
    principal: Actor,
) -> EcommerceListingDetail:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    return service.detail(task_id)


@router.get("/ecommerce/listing-tasks/{task_id}/export")
def export_listing_task_package(
    task_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> Response:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    data, filename = service.export_listing_package(
        task_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.patch(
    "/ecommerce/listing-tasks/{task_id}/content",
    response_model=EcommerceListingDetail,
)
def update_listing_content(
    task_id: UUID,
    payload: EcommerceListingContentUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceListingDetail:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    task = service.update_listing_content(
        task_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.detail(task.id)


@router.post(
    "/ecommerce/listing-tasks/{task_id}/storyboard/generate",
    response_model=EcommerceImageBatchGenerateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited())],
)
def generate_listing_storyboard(
    task_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceImageBatchGenerateResponse:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    assets = service.generate_listing_storyboard(
        task_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return EcommerceImageBatchGenerateResponse(
        items=[service.asset_view(asset) for asset in assets]
    )


@router.post(
    "/ecommerce/listing-tasks/{task_id}/storyboard/video",
    response_model=EcommerceProductAssetView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited())],
)
def render_listing_storyboard_video(
    task_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> EcommerceProductAssetView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    asset = service.render_listing_storyboard_video(
        task_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    return service.asset_view(asset)


@router.post(
    "/ecommerce/listing-tasks/{task_id}/storyboard/video-jobs",
    response_model=EcommerceVideoRenderJobView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited())],
)
def create_listing_storyboard_video_job(
    task_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
    payload: EcommerceVideoRenderJobCreate | None = None,
) -> EcommerceVideoRenderJobView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    job, event = service.create_video_render_job(
        task_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
        options=payload,
    )
    if event is not None:
        background_tasks.add_task(dispatch_outbox_event, event.id)
    return service.video_render_job_view(job)


@router.get(
    "/ecommerce/listing-tasks/{task_id}/video-render-jobs",
    response_model=EcommerceVideoRenderJobListResponse,
)
def list_listing_storyboard_video_jobs(
    task_id: UUID,
    db: DbSession,
    principal: Actor,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> EcommerceVideoRenderJobListResponse:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    return service.list_video_render_jobs(task_id, limit=limit)


@router.get(
    "/ecommerce/video-render-jobs/{job_id}",
    response_model=EcommerceVideoRenderJobView,
)
def get_storyboard_video_job(
    job_id: UUID,
    db: DbSession,
    principal: Actor,
) -> EcommerceVideoRenderJobView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    return service.video_render_job_view(
        _video_render_job_for_access(service, job_id, principal)
    )


@router.post(
    "/ecommerce/video-render-jobs/{job_id}/retry",
    response_model=EcommerceVideoRenderJobView,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited())],
)
def retry_storyboard_video_job(
    job_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> EcommerceVideoRenderJobView:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _video_render_job_for_access(service, job_id, principal)
    job, event = service.retry_video_render_job(
        job_id,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    if event is not None:
        background_tasks.add_task(dispatch_outbox_event, event.id)
    return service.video_render_job_view(job)


@router.post(
    "/ecommerce/listing-tasks/{task_id}/reviews",
    response_model=EcommerceListingMutation,
)
def review_listing_task(
    task_id: UUID,
    payload: EcommerceListingReview,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> EcommerceListingMutation:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    task, event = service.review(
        task_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    if event is not None:
        background_tasks.add_task(dispatch_outbox_event, event.id)
    return EcommerceListingMutation(
        task_id=task.id,
        version=task.version,
        status=task.status,
        message=(
            "Listing approved and publish queued."
            if event is not None
            else "Listing review recorded."
        ),
    )


@router.post(
    "/ecommerce/listing-tasks/{task_id}/retry",
    response_model=EcommerceListingMutation,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_listing_publish(
    task_id: UUID,
    payload: EcommerceListingRetryRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
) -> EcommerceListingMutation:
    ensure_ticket_writer(principal)
    service = EcommerceService(db)
    _listing_task_for_access(service, task_id, principal)
    task, event = service.retry_publish(
        task_id,
        payload,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )
    background_tasks.add_task(dispatch_outbox_event, event.id)
    return EcommerceListingMutation(
        task_id=task.id,
        version=task.version,
        status=task.status,
        message="Listing publish retry queued.",
    )
