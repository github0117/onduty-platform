import json
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from ticket_agent.agent_runs.router import router as agent_run_router
from ticket_agent.agent_skills.router import router as agent_skill_router
from ticket_agent.api.router import router
from ticket_agent.business_entries.router import router as business_entries_router
from ticket_agent.customer_service.router import router as customer_service_router
from ticket_agent.digital_employees.draft_router import (
    router as employee_draft_router,
)
from ticket_agent.digital_employees.router import router as employee_router
from ticket_agent.ecommerce.router import router as ecommerce_router
from ticket_agent.identity.dependencies import (
    ensure_business_unit_access,
    get_principal,
    resolve_business_unit,
    tenant_query_guard,
)
from ticket_agent.identity.models import Principal
from ticket_agent.integrations.metrics import SyncMetricsService
from ticket_agent.integrations.router import router as integration_router
from ticket_agent.knowledge.metrics import RagMetricsService
from ticket_agent.knowledge.router import router as knowledge_router
from ticket_agent.logistics.router import router as logistics_router
from ticket_agent.mcp_connectors.router import router as mcp_connector_router
from ticket_agent.model_gateway.router import router as model_router
from ticket_agent.model_gateway.usage import ModelUsageService
from ticket_agent.observability.exporter import (
    authorize_metrics,
    render_labeled_prometheus_metrics,
)
from ticket_agent.shared.body_limit import enforce_request_body_limit
from ticket_agent.shared.db import SessionLocal, engine, init_db
from ticket_agent.shared.errors import ApiProblem, api_problem_handler
from ticket_agent.shared.settings import get_settings
from ticket_agent.tickets.schemas import HealthResponse
from ticket_agent.tools.metrics import ToolMetricsService
from ticket_agent.tools.router import router as tool_router
from ticket_agent.workforce.router import router as workforce_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    if settings.is_development:
        init_db()
    yield


settings = get_settings()
demo_reset_lock = Lock()
DEMO_RESET_DB_LOCK_KEY = 84739021
DEMO_RESET_BUSINESS_UNIT = "bu_demo"
DEMO_RESET_CONFIRMATION = "reset-bu_demo"
demo_reset_jobs: dict[str, dict[str, object]] = {}
demo_reset_jobs_lock = Lock()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Domestic e-commerce digital worker MVP",
    lifespan=lifespan,
)
app.add_exception_handler(ApiProblem, api_problem_handler)


@app.exception_handler(OperationalError)
async def database_operational_error_handler(
    request: Request,
    exc: OperationalError,
) -> JSONResponse:
    message = str(exc.orig)
    database_busy = "database is locked" in message.lower()
    return JSONResponse(
        status_code=503 if database_busy else 500,
        media_type="application/problem+json",
        content={
            "type": (
                "https://api.example.com/problems/database-busy"
                if database_busy
                else "https://api.example.com/problems/database-error"
            ),
            "title": (
                "Demo database is busy"
                if database_busy
                else "Database operation failed"
            ),
            "status": 503 if database_busy else 500,
            "detail": (
                "演示数据库正在处理其他任务，请等待片刻后重试。"
                if database_busy
                else "数据库操作失败，请稍后重试。"
            ),
            "code": "DATABASE_BUSY" if database_busy else "DATABASE_ERROR",
            "correlation_id": request.state.correlation_id,
            "retryable": database_busy,
        },
    )


@app.middleware("http")
async def tenant_body_guard(request: Request, call_next: object) -> object:
    if (
        request.url.path.startswith(settings.api_prefix)
        and request.method in {"POST", "PUT", "PATCH"}
        and request.headers.get("content-type", "")
        .lower()
        .startswith("application/json")
    ):
        body = await request.body()

        async def replay_body() -> dict[str, object]:
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        request._receive = replay_body
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            business_unit_id = payload.get("business_unit_id")
            if isinstance(business_unit_id, str):
                try:
                    principal = get_principal(
                        authorization=request.headers.get(
                            "authorization"
                        ),
                        x_actor_id=request.headers.get("x-actor-id"),
                        x_actor_role=request.headers.get(
                            "x-actor-role",
                            "agent",
                        ),
                        x_business_unit_id=request.headers.get(
                            "x-business-unit-id"
                        ),
                        x_business_units=request.headers.get(
                            "x-business-units"
                        ),
                    )
                    ensure_business_unit_access(
                        principal,
                        business_unit_id,
                    )
                except ApiProblem as exc:
                    return await api_problem_handler(request, exc)
    return await call_next(request)  # type: ignore[operator]


# Middleware is applied from the inside out: later registrations wrap earlier
# ones. The body limit runs before tenant_body_guard reads the payload, while
# CORS stays outside it so rejected requests still receive CORS headers.
app.middleware("http")(enforce_request_body_limit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: object) -> object:
    incoming = request.headers.get("X-Correlation-ID")
    request.state.correlation_id = incoming[:64] if incoming else str(uuid4())
    response = await call_next(request)  # type: ignore[operator]
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


@app.get("/health/live", response_model=HealthResponse, tags=["health"])
def health_live() -> HealthResponse:
    return HealthResponse(
        status="ok",
        database="not_checked",
        environment=settings.app_env,
    )


@app.get("/health/ready", response_model=HealthResponse, tags=["health"])
def health_ready() -> HealthResponse:
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database="ok",
        environment=settings.app_env,
    )


tenant_dependencies = [Depends(tenant_query_guard)]
app.include_router(
    router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)


def _demo_reset_now() -> str:
    return datetime.now(UTC).isoformat()


def _update_demo_reset_job(job_id: str, **updates: object) -> None:
    with demo_reset_jobs_lock:
        job = demo_reset_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)
        job["updated_at"] = _demo_reset_now()


def _prune_demo_reset_jobs_locked() -> None:
    if len(demo_reset_jobs) <= 20:
        return
    finished = sorted(
        (
            (job_id, str(job.get("created_at", "")))
            for job_id, job in demo_reset_jobs.items()
            if job.get("status") in {"SUCCEEDED", "FAILED"}
        ),
        key=lambda item: item[1],
    )
    for job_id, _created_at in finished[: len(demo_reset_jobs) - 20]:
        demo_reset_jobs.pop(job_id, None)


def _run_demo_reset_job(job_id: str) -> None:
    lock_connection = None
    acquired = False
    try:
        if engine.dialect.name == "postgresql":
            lock_connection = engine.connect()
            acquired = bool(
                lock_connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": DEMO_RESET_DB_LOCK_KEY},
                ).scalar()
            )
        else:
            acquired = demo_reset_lock.acquire(blocking=False)
        if not acquired:
            _update_demo_reset_job(
                job_id,
                status="FAILED",
                code="DEMO_RESET_IN_PROGRESS",
                message="另一项演示数据恢复正在运行，请稍后重试。",
                finished_at=_demo_reset_now(),
            )
            return
        _update_demo_reset_job(
            job_id,
            status="RUNNING",
            message="正在检查并恢复演示数据。",
        )
        script = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_data.py"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    settings.demo_reset_base_url,
                ],
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
        except subprocess.TimeoutExpired:
            _update_demo_reset_job(
                job_id,
                status="FAILED",
                code="DEMO_RESET_TIMEOUT",
                message="演示数据恢复超时，请稍后重试。",
                finished_at=_demo_reset_now(),
            )
            return
        if completed.returncode != 0:
            _update_demo_reset_job(
                job_id,
                status="FAILED",
                code="DEMO_RESET_FAILED",
                message="演示数据恢复失败，请查看服务端日志。",
                finished_at=_demo_reset_now(),
            )
            return
        _update_demo_reset_job(
            job_id,
            status="SUCCEEDED",
            code=None,
            message="演示数据已检查并恢复。",
            finished_at=_demo_reset_now(),
        )
    except Exception:
        _update_demo_reset_job(
            job_id,
            status="FAILED",
            code="DEMO_RESET_FAILED",
            message="演示数据恢复失败，请查看服务端日志。",
            finished_at=_demo_reset_now(),
        )
    finally:
        if lock_connection is not None:
            lock_connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": DEMO_RESET_DB_LOCK_KEY},
            )
            lock_connection.close()
        elif acquired:
            demo_reset_lock.release()


@app.post(
    f"{settings.api_prefix}/demo/reset",
    tags=["demo"],
    status_code=202,
)
def reset_demo_data(
    background_tasks: BackgroundTasks,
    principal: Annotated[Principal, Depends(get_principal)],
    business_unit_id: Annotated[str | None, Query()] = None,
    x_demo_reset_confirm: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Administrator role required",
            detail="Demo reset is restricted to platform administrators.",
        )
    if (
        not settings.demo_reset_enabled
        or settings.app_env not in {"development", "test"}
    ):
        raise ApiProblem(
            status_code=403,
            code="DEMO_RESET_DISABLED",
            title="Demo reset is disabled",
            detail="Demo reset is only available in a demo or development environment.",
        )
    if x_demo_reset_confirm != DEMO_RESET_CONFIRMATION:
        raise ApiProblem(
            status_code=403,
            code="DEMO_RESET_CONFIRMATION_REQUIRED",
            title="Demo reset confirmation required",
            detail="Confirm that only the demo tenant should be restored.",
        )
    resolved_business_unit = resolve_business_unit(
        principal,
        business_unit_id,
    )
    if resolved_business_unit != DEMO_RESET_BUSINESS_UNIT:
        raise ApiProblem(
            status_code=409,
            code="DEMO_RESET_UNIT_UNSUPPORTED",
            title="Demo reset is scoped to the demo tenant",
            detail="The demo seed only restores the bu_demo sandbox.",
        )
    with demo_reset_jobs_lock:
        _prune_demo_reset_jobs_locked()
        if any(
            job.get("status") in {"QUEUED", "RUNNING"}
            for job in demo_reset_jobs.values()
        ):
            raise ApiProblem(
                status_code=409,
                code="DEMO_RESET_IN_PROGRESS",
                title="Demo reset is already running",
                detail="演示数据正在恢复，请等待当前任务完成后再试。",
            )
        job_id = str(uuid4())
        created_at = _demo_reset_now()
        demo_reset_jobs[job_id] = {
            "job_id": job_id,
            "business_unit_id": resolved_business_unit,
            "status": "QUEUED",
            "message": "演示数据恢复任务已排队。",
            "code": None,
            "created_by": principal.actor_id,
            "created_at": created_at,
            "updated_at": created_at,
            "finished_at": None,
        }
    background_tasks.add_task(_run_demo_reset_job, job_id)
    return {
        "job_id": job_id,
        "business_unit_id": resolved_business_unit,
        "status": "QUEUED",
        "message": "演示数据恢复任务已排队。",
    }


@app.get(f"{settings.api_prefix}/demo/reset/{{job_id}}", tags=["demo"])
def get_demo_reset_status(
    job_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    if principal.role != "admin":
        raise ApiProblem(
            status_code=403,
            code="FORBIDDEN",
            title="Administrator role required",
            detail="Demo reset status is restricted to platform administrators.",
        )
    with demo_reset_jobs_lock:
        job = demo_reset_jobs.get(job_id)
        snapshot = dict(job) if job is not None else None
    if snapshot is None:
        raise ApiProblem(
            status_code=404,
            code="DEMO_RESET_JOB_NOT_FOUND",
            title="Demo reset job not found",
            detail="The demo reset job does not exist or has expired.",
        )
    ensure_business_unit_access(
        principal,
        str(snapshot["business_unit_id"]),
    )
    return snapshot


app.include_router(
    knowledge_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    integration_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    employee_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    employee_draft_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    customer_service_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    business_entries_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    tool_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    model_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    agent_run_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    ecommerce_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    logistics_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    agent_skill_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    mcp_connector_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)
app.include_router(
    workforce_router,
    prefix=settings.api_prefix,
    dependencies=tenant_dependencies,
)


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(
    authorization: str | None = Header(default=None),
) -> PlainTextResponse:
    authorize_metrics(authorization, settings)
    with SessionLocal() as session:
        sync_service = SyncMetricsService(session)
        rag_service = RagMetricsService(session)
        tool_service = ToolMetricsService(session)
        model_service = ModelUsageService(session)
        business_units = sync_service.business_units() or [""]
        series = [
            (
                {
                    "business_unit": business_unit or "all",
                    "adapter": settings.ticket_integration_provider,
                },
                sync_service.summary(business_unit_id=business_unit or None),
                rag_service.summary(business_unit_id=business_unit or None),
                tool_service.summary(business_unit_id=business_unit or None),
                model_service.summary(business_unit_id=business_unit or None),
            )
            for business_unit in business_units
        ]
    return PlainTextResponse(
        render_labeled_prometheus_metrics(series),
        media_type="text/plain; version=0.0.4",
    )

