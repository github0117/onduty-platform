from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from ticket_agent.api.dependencies import Actor, DbSession, correlation_id
from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    ensure_knowledge_admin,
    ensure_knowledge_worker,
    ensure_metrics_viewer,
    ensure_ticket_writer,
    ensure_workspace_viewer,
    resolve_business_unit,
)
from ticket_agent.identity.models import Principal
from ticket_agent.knowledge.evaluation_service import KnowledgeEvaluationService
from ticket_agent.knowledge.feedback_service import KnowledgeFeedbackService
from ticket_agent.knowledge.metrics import RagMetricsService
from ticket_agent.knowledge.models import (
    KnowledgeDocument,
    KnowledgeEvaluationCase,
    KnowledgeEvaluationRun,
    KnowledgeRepairTask,
)
from ticket_agent.knowledge.product_sync import sync_product_knowledge_batch
from ticket_agent.knowledge.repair_service import KnowledgeRepairService
from ticket_agent.knowledge.schemas import (
    EmployeeKnowledgeBindingReplace,
    EmployeeKnowledgeBindingView,
    KnowledgeDocumentCreate,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentView,
    KnowledgeEvaluationCaseCreate,
    KnowledgeEvaluationCaseUpdate,
    KnowledgeEvaluationCaseView,
    KnowledgeEvaluationRunCreate,
    KnowledgeEvaluationRunList,
    KnowledgeEvaluationRunView,
    KnowledgeFeedbackClusterList,
    KnowledgeFeedbackCreate,
    KnowledgeFeedbackList,
    KnowledgeFeedbackView,
    KnowledgeHitView,
    KnowledgePublishRequest,
    KnowledgeRepairTaskList,
    KnowledgeRepairTaskUpdate,
    KnowledgeRepairTaskView,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
    KnowledgeSpaceView,
    KnowledgeUploadAccepted,
    KnowledgeVersionCreate,
    KnowledgeVersionView,
    ProductKnowledgeSyncRequest,
    ProductKnowledgeSyncResult,
    RagMetricsResponse,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.outbox.service import dispatch_outbox_event
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.rate_limit import rate_limited

router = APIRouter()


def _document_for_access(
    service: KnowledgeService,
    document_id: UUID,
    principal: Principal,
) -> KnowledgeDocument:
    document = service.get_document(document_id)
    ensure_business_unit_access(principal, document.business_unit_id)
    return document


def _repair_task_for_access(
    service: KnowledgeRepairService,
    task_id: UUID,
    principal: Principal,
) -> KnowledgeRepairTask:
    task = service.get(task_id)
    ensure_business_unit_access(principal, task.business_unit_id)
    return task


def _evaluation_case_for_access(
    service: KnowledgeEvaluationService,
    case_id: UUID,
    principal: Principal,
) -> KnowledgeEvaluationCase:
    case = service.get_case(case_id)
    ensure_business_unit_access(principal, case.business_unit_id)
    return case


def _evaluation_run_for_access(
    service: KnowledgeEvaluationService,
    run_id: UUID,
    principal: Principal,
) -> KnowledgeEvaluationRun:
    run = service.get_run(run_id)
    ensure_business_unit_access(principal, run.business_unit_id)
    return run


@router.post(
    "/knowledge/feedback",
    response_model=KnowledgeFeedbackView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_feedback(
    payload: KnowledgeFeedbackCreate,
    db: DbSession,
    principal: Actor,
) -> KnowledgeFeedbackView:
    ensure_ticket_writer(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = KnowledgeFeedbackService(db)
    return service.view(service.create(payload, actor_id=principal.actor_id))


@router.get(
    "/knowledge/feedback",
    response_model=KnowledgeFeedbackList,
)
def list_knowledge_feedback(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> KnowledgeFeedbackList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return KnowledgeFeedbackService(db).list(business_unit_id=business_unit_id)


@router.get(
    "/knowledge/feedback/clusters",
    response_model=KnowledgeFeedbackClusterList,
)
def cluster_knowledge_feedback(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
) -> KnowledgeFeedbackClusterList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return KnowledgeFeedbackService(db).clusters(business_unit_id=business_unit_id)


@router.get(
    "/knowledge/repair-tasks",
    response_model=KnowledgeRepairTaskList,
)
def list_knowledge_repair_tasks(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    repair_status: Annotated[str | None, Query(alias="status")] = None,
) -> KnowledgeRepairTaskList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return KnowledgeRepairService(db).list(
        business_unit_id=business_unit_id,
        status=repair_status,
    )


@router.patch(
    "/knowledge/repair-tasks/{task_id}",
    response_model=KnowledgeRepairTaskView,
)
def update_knowledge_repair_task(
    task_id: UUID,
    payload: KnowledgeRepairTaskUpdate,
    db: DbSession,
    principal: Actor,
) -> KnowledgeRepairTaskView:
    ensure_knowledge_admin(principal)
    service = KnowledgeRepairService(db)
    _repair_task_for_access(service, task_id, principal)
    return service.view(service.update(task_id, payload))


@router.post(
    "/knowledge/repair-tasks/{task_id}/verify",
    response_model=KnowledgeRepairTaskView,
    dependencies=[Depends(rate_limited())],
)
def verify_knowledge_repair_task(
    task_id: UUID,
    db: DbSession,
    principal: Actor,
) -> KnowledgeRepairTaskView:
    ensure_knowledge_worker(principal)
    service = KnowledgeRepairService(db)
    _repair_task_for_access(service, task_id, principal)
    return service.view(service.verify(task_id))


@router.post(
    "/knowledge/evaluation-cases",
    response_model=KnowledgeEvaluationCaseView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_evaluation_case(
    payload: KnowledgeEvaluationCaseCreate,
    db: DbSession,
    principal: Actor,
) -> KnowledgeEvaluationCaseView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = KnowledgeEvaluationService(db)
    case = service.create_case(payload, actor_id=principal.actor_id)
    return service.case_view(case)


@router.get(
    "/knowledge/evaluation-cases",
    response_model=list[KnowledgeEvaluationCaseView],
)
def list_knowledge_evaluation_cases(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    knowledge_space_id: Annotated[UUID | None, Query()] = None,
) -> list[KnowledgeEvaluationCaseView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = KnowledgeEvaluationService(db)
    return [
        service.case_view(case)
        for case in service.list_cases(
            business_unit_id=business_unit_id,
            knowledge_space_id=knowledge_space_id,
        )
    ]


@router.patch(
    "/knowledge/evaluation-cases/{case_id}",
    response_model=KnowledgeEvaluationCaseView,
)
def update_knowledge_evaluation_case(
    case_id: UUID,
    payload: KnowledgeEvaluationCaseUpdate,
    db: DbSession,
    principal: Actor,
) -> KnowledgeEvaluationCaseView:
    ensure_knowledge_admin(principal)
    service = KnowledgeEvaluationService(db)
    _evaluation_case_for_access(service, case_id, principal)
    return service.case_view(service.update_case(case_id, payload))


@router.post(
    "/knowledge/evaluation-runs",
    response_model=KnowledgeEvaluationRunView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limited())],
)
def run_knowledge_evaluation(
    payload: KnowledgeEvaluationRunCreate,
    db: DbSession,
    principal: Actor,
) -> KnowledgeEvaluationRunView:
    ensure_knowledge_worker(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = KnowledgeEvaluationService(db)
    run = service.run(payload, actor_id=principal.actor_id)
    return service.run_view(run)


@router.get(
    "/knowledge/evaluation-runs",
    response_model=KnowledgeEvaluationRunList,
)
def list_knowledge_evaluation_runs(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> KnowledgeEvaluationRunList:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    return KnowledgeEvaluationService(db).list_runs(
        business_unit_id=business_unit_id,
        limit=limit,
    )


@router.get(
    "/knowledge/evaluation-runs/{run_id}",
    response_model=KnowledgeEvaluationRunView,
)
def get_knowledge_evaluation_run(
    run_id: UUID,
    db: DbSession,
    principal: Actor,
) -> KnowledgeEvaluationRunView:
    ensure_workspace_viewer(principal)
    service = KnowledgeEvaluationService(db)
    run = _evaluation_run_for_access(service, run_id, principal)
    return service.run_view(run)


@router.post(
    "/knowledge/product-sync",
    response_model=ProductKnowledgeSyncResult,
)
def sync_product_knowledge_cards(
    payload: ProductKnowledgeSyncRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> ProductKnowledgeSyncResult:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    return sync_product_knowledge_batch(
        db,
        business_unit_id=payload.business_unit_id,
        product_ids=payload.product_ids,
        actor_id=principal.actor_id,
        correlation_id=correlation_id(request),
    )


@router.post(
    "/knowledge-spaces",
    response_model=KnowledgeSpaceView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_space(
    payload: KnowledgeSpaceCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeSpaceView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    ensure_business_unit_access(
        principal,
        payload.business_unit_id,
    )
    space = service.create_space(payload)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.space.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_space",
        resource_id=space.id,
        action="create",
        decision="EXECUTED",
        payload={
            "business_unit_id": space.business_unit_id,
            "code": space.code,
        },
    )
    db.commit()
    return service.space_view(space)


@router.patch(
    "/knowledge-spaces/{space_id}",
    response_model=KnowledgeSpaceView,
)
def update_knowledge_space(
    space_id: UUID,
    payload: KnowledgeSpaceUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeSpaceView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    ensure_business_unit_access(
        principal,
        service.get_space(space_id).business_unit_id,
    )
    space = service.update_space(
        space_id,
        payload,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.space.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_space",
        resource_id=space.id,
        action="update",
        decision="EXECUTED",
        payload=payload.model_dump(mode="json", exclude_none=True),
    )
    db.commit()
    return service.space_view(space)


@router.get("/knowledge-spaces", response_model=list[KnowledgeSpaceView])
def list_knowledge_spaces(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
) -> list[KnowledgeSpaceView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(
        principal,
        business_unit_id,
    )
    service = KnowledgeService(db)
    return [
        service.space_view(space)
        for space in service.list_spaces(business_unit_id)
    ]


@router.get(
    "/digital-employees/{employee_id}/knowledge-bindings",
    response_model=list[EmployeeKnowledgeBindingView],
)
def list_employee_knowledge_bindings(
    employee_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeKnowledgeBindingView]:
    ensure_workspace_viewer(principal)
    service = KnowledgeService(db)
    employee = service.session.get(
        DigitalEmployee,
        employee_id,
    )
    if employee is None:
        raise ApiProblem(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            title="Digital employee not found",
            detail=f"Digital employee {employee_id} does not exist.",
        )
    ensure_business_unit_access(
        principal,
        employee.business_unit_id,
    )
    return [
        service.binding_view(binding)
        for binding in service.list_employee_bindings(employee_id)
    ]


@router.put(
    "/digital-employees/{employee_id}/knowledge-bindings",
    response_model=list[EmployeeKnowledgeBindingView],
)
def replace_employee_knowledge_bindings(
    employee_id: UUID,
    payload: EmployeeKnowledgeBindingReplace,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> list[EmployeeKnowledgeBindingView]:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    employee = service.session.get(
        DigitalEmployee,
        employee_id,
    )
    if employee is None:
        raise ApiProblem(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            title="Digital employee not found",
            detail=f"Digital employee {employee_id} does not exist.",
        )
    ensure_business_unit_access(
        principal,
        employee.business_unit_id,
    )
    bindings = service.replace_employee_bindings(
        employee_id,
        bindings=[
            binding.model_dump()
            for binding in payload.bindings
        ],
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.employee_bindings.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="digital_employee",
        resource_id=employee_id,
        action="update_knowledge_bindings",
        decision="EXECUTED",
        payload={"binding_count": len(bindings)},
    )
    db.commit()
    return [service.binding_view(binding) for binding in bindings]


@router.post(
    "/knowledge-documents",
    response_model=KnowledgeDocumentView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_document(
    payload: KnowledgeDocumentCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeDocumentView:
    ensure_knowledge_admin(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = KnowledgeService(db)
    document = service.create_document(payload, actor_id=principal.actor_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.document.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_document",
        resource_id=document.id,
        action="create",
        decision="EXECUTED",
        payload={
            "business_unit_id": document.business_unit_id,
            "space_id": str(document.space_id) if document.space_id else None,
            "title": document.title,
        },
    )
    db.commit()
    return service.document_view(document)


@router.patch(
    "/knowledge-documents/{document_id}",
    response_model=KnowledgeDocumentView,
)
def update_knowledge_document(
    document_id: UUID,
    payload: KnowledgeDocumentUpdate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeDocumentView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    document = service.update_document(document_id, payload)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.document.updated",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_document",
        resource_id=document.id,
        action="update",
        decision="EXECUTED",
        payload=payload.model_dump(mode="json", exclude_none=True),
    )
    db.commit()
    return service.document_view(document)


@router.post(
    "/knowledge-documents/{document_id}/archive",
    response_model=KnowledgeDocumentView,
)
def archive_knowledge_document(
    document_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeDocumentView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    document = service.archive_document(document_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.document.archived",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_document",
        resource_id=document.id,
        action="archive",
        decision="EXECUTED",
    )
    db.commit()
    return service.document_view(document)


@router.post(
    "/knowledge-documents/{document_id}/restore",
    response_model=KnowledgeDocumentView,
)
def restore_knowledge_document(
    document_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeDocumentView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    document = service.restore_document(document_id)
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.document.restored",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_document",
        resource_id=document.id,
        action="restore",
        decision="EXECUTED",
    )
    db.commit()
    return service.document_view(document)


@router.get("/knowledge-documents", response_model=list[KnowledgeDocumentView])
def list_knowledge_documents(
    db: DbSession,
    principal: Actor,
    business_unit_id: str | None = Query(default=None),
    space_id: Annotated[UUID | None, Query()] = None,
) -> list[KnowledgeDocumentView]:
    ensure_workspace_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    service = KnowledgeService(db)
    return [
        service.document_view(document)
        for document in service.list_documents(business_unit_id, space_id)
    ]


@router.post(
    "/knowledge-documents/{document_id}/versions",
    response_model=KnowledgeVersionView,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_version(
    document_id: UUID,
    payload: KnowledgeVersionCreate,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeVersionView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    version = service.create_version(
        document_id,
        payload,
        correlation_id=correlation_id(request),
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.version.created",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_version",
        resource_id=version.id,
        action="create_version",
        decision="EXECUTED",
        payload={
            "document_id": str(document_id),
            "version_label": version.version_label,
            "content_hash": version.content_hash,
        },
    )
    db.commit()
    return service.version_view(version)


@router.post(
    "/knowledge-documents/{document_id}/uploads",
    response_model=KnowledgeUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_knowledge_version_async(
    document_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSession,
    principal: Actor,
    version_label: str = Query(min_length=1, max_length=64),
    filename: str = Query(min_length=1, max_length=255),
) -> KnowledgeUploadAccepted:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    data = await request.body()
    version, outbox_event_id = service.create_async_upload(
        document_id,
        version_label=version_label,
        filename=filename,
        content_type=request.headers.get("content-type", "application/octet-stream"),
        data=data,
        correlation_id=correlation_id(request),
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.version.uploaded",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_version",
        resource_id=version.id,
        action="upload",
        decision="EXECUTED",
        payload={
            "document_id": str(document_id),
            "version_label": version.version_label,
            "source_filename": version.source_filename,
            "source_size_bytes": version.source_size_bytes,
            "source_object_key": version.source_object_key,
        },
    )
    db.commit()
    background_tasks.add_task(dispatch_outbox_event, outbox_event_id)
    return KnowledgeUploadAccepted(
        version_id=version.id,
        document_id=document_id,
        version_label=version.version_label,
        status=version.status,
        source_object_key=version.source_object_key or "",
    )


@router.get(
    "/knowledge-documents/{document_id}/versions/{version_id}",
    response_model=KnowledgeVersionView,
)
def get_knowledge_version(
    document_id: UUID,
    version_id: UUID,
    db: DbSession,
    principal: Actor,
) -> KnowledgeVersionView:
    ensure_workspace_viewer(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    return service.version_view(service.get_version(document_id, version_id))


@router.get(
    "/knowledge-documents/{document_id}/versions",
    response_model=list[KnowledgeVersionView],
)
def list_knowledge_versions(
    document_id: UUID,
    db: DbSession,
    principal: Actor,
) -> list[KnowledgeVersionView]:
    ensure_workspace_viewer(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    return [
        service.version_view(version)
        for version in service.list_versions(document_id)
    ]


@router.post(
    "/knowledge-documents/{document_id}/versions/from-file",
    response_model=KnowledgeVersionView,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_version_from_file(
    document_id: UUID,
    request: Request,
    db: DbSession,
    principal: Actor,
    version_label: str = Query(min_length=1, max_length=64),
    filename: str = Query(min_length=1, max_length=255),
) -> KnowledgeVersionView:
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    data = await request.body()
    version = service.create_version_from_file(
        document_id,
        version_label=version_label,
        filename=filename,
        content_type=request.headers.get("content-type", "application/octet-stream"),
        data=data,
        correlation_id=correlation_id(request),
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.version.file_ingested",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_version",
        resource_id=version.id,
        action="ingest_file",
        decision="EXECUTED",
        payload={
            "document_id": str(document_id),
            "version_label": version.version_label,
            "source_filename": version.source_filename,
            "parser_name": version.parser_name,
            "source_size_bytes": version.source_size_bytes,
        },
    )
    db.commit()
    return service.version_view(version)


@router.post(
    "/knowledge-documents/{document_id}/versions/{version_id}/publish",
    response_model=KnowledgeVersionView,
)
def publish_knowledge_version(
    document_id: UUID,
    version_id: UUID,
    payload: KnowledgePublishRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeVersionView:
    del payload
    ensure_knowledge_admin(principal)
    service = KnowledgeService(db)
    _document_for_access(service, document_id, principal)
    version = KnowledgeEvaluationService(db).publish_with_gate(
        document_id=document_id,
        version_id=version_id,
        actor_id=principal.actor_id,
    )
    record_audit(
        db,
        correlation_id=correlation_id(request),
        event_type="knowledge.version.published",
        actor_type="USER",
        actor_id=principal.actor_id,
        resource_type="knowledge_version",
        resource_id=version.id,
        action="publish",
        decision="EXECUTED",
        payload={
            "document_id": str(document_id),
            "version_label": version.version_label,
        },
    )
    db.commit()
    return service.version_view(version)


@router.post(
    "/knowledge/search",
    response_model=KnowledgeSearchResponse,
    dependencies=[Depends(rate_limited())],
)
def search_knowledge(
    payload: KnowledgeSearchRequest,
    request: Request,
    db: DbSession,
    principal: Actor,
) -> KnowledgeSearchResponse:
    ensure_workspace_viewer(principal)
    ensure_business_unit_access(principal, payload.business_unit_id)
    service = KnowledgeService(db)
    hits = service.search(
        query=payload.query,
        business_unit_id=payload.business_unit_id,
        space_id=payload.space_id,
        employee_id=payload.employee_id,
        scope=payload.scope,
        top_k=payload.top_k,
        correlation_id=correlation_id(request),
    )
    return KnowledgeSearchResponse(
        items=[
            KnowledgeHitView(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                space_id=hit.space_id,
                title=hit.title,
                version=hit.version,
                content=hit.content,
                score=hit.score,
            )
            for hit in hits
        ],
        embedding_model=service.embedding_provider.name,
        reranker=service.reranker.name,
    )


@router.get("/metrics/rag", response_model=RagMetricsResponse)
def get_rag_metrics(
    db: DbSession,
    principal: Actor,
    business_unit_id: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query()] = None,
    to_at: Annotated[datetime | None, Query()] = None,
) -> RagMetricsResponse:
    ensure_metrics_viewer(principal)
    business_unit_id = resolve_business_unit(principal, business_unit_id)
    payload = RagMetricsService(db).summary(
        business_unit_id=business_unit_id,
        from_at=from_at,
        to_at=to_at,
    )
    return RagMetricsResponse.model_validate(payload)

