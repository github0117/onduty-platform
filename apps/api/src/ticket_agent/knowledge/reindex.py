from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.embedding_types import EmbeddingProvider
from ticket_agent.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeReindexJob,
    KnowledgeVersion,
)
from ticket_agent.knowledge.service import KnowledgeService
from ticket_agent.knowledge.tokenizer import LEXICAL_TOKENIZER_VERSION
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import Settings, get_settings

MAX_REINDEX_ATTEMPTS = 3
STALE_RUNNING_AFTER = timedelta(minutes=30)
# FAILED jobs are reusable: re-requesting the same scope retries them instead of
# piling up duplicate rows, and the attempt counter drives the dead-letter rule.
ACTIVE_STATUSES = ("PENDING", "RUNNING", "FAILED")


@dataclass(frozen=True)
class ReindexJobSubmission:
    job: KnowledgeReindexJob
    created: bool


class KnowledgeReindexService:
    """Rebuild chunk vectors for existing versions without re-parsing files."""

    def __init__(
        self,
        session: Session,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_provider = embedding_provider or get_embedding_provider()

    @property
    def target_embedding_model(self) -> str:
        return self.embedding_provider.name

    def create_job(
        self,
        *,
        business_unit_id: str,
        requested_by: str,
        correlation_id: str,
        document_id: UUID | None = None,
        chunking_version: str | None = None,
    ) -> ReindexJobSubmission:
        target_chunking_version = chunking_version or self.settings.knowledge_chunking_version
        if target_chunking_version not in {"v1", "v2"}:
            raise ApiProblem(
                status_code=422,
                code="SCHEMA_VALIDATION_FAILED",
                title="Invalid chunking version",
                detail="chunking_version must be 'v1' or 'v2'.",
            )
        self._lock_scope(business_unit_id, document_id)
        active = self._active_job(business_unit_id, document_id)
        if active is not None:
            if active.target_embedding_model == self.target_embedding_model:
                return ReindexJobSubmission(job=active, created=False)
            raise ApiProblem(
                status_code=409,
                code="REINDEX_IN_PROGRESS",
                title="Reindex already in progress",
                detail=(
                    "Another reindex job is running for this scope with a "
                    "different target embedding model."
                ),
            )
        job = KnowledgeReindexJob(
            business_unit_id=business_unit_id,
            document_id=document_id,
            target_embedding_model=self.target_embedding_model,
            target_chunking_version=target_chunking_version,
            status="PENDING",
            total_versions=self._count_versions(business_unit_id, document_id),
            requested_by=requested_by,
            correlation_id=correlation_id,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return ReindexJobSubmission(job=job, created=True)

    def run_job(
        self,
        job_id: UUID,
        *,
        correlation_id: str | None = None,
    ) -> KnowledgeReindexJob:
        job = self._lock_job(job_id)
        if job is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Reindex job not found",
                detail=f"Reindex job {job_id} does not exist.",
            )
        if job.status in {"SUCCEEDED", "DEAD_LETTER"}:
            return job
        if job.status == "RUNNING" and not self._is_stale(job):
            return job

        now = datetime.now(UTC)
        job.status = "RUNNING"
        job.started_at = now
        job.finished_at = None
        job.attempt_count += 1
        job.last_error = None
        self.session.commit()

        processed = job.processed_versions
        skipped = job.skipped_versions
        failed = job.failed_versions
        knowledge_service = KnowledgeService(
            self.session,
            embedding_provider=self.embedding_provider,
        )
        for version_id in self._version_ids(job):
            if self._version_is_current(version_id, job):
                skipped += 1
                continue
            try:
                rebuilt = knowledge_service.rebuild_version_chunks(
                    version_id,
                    chunking_version=job.target_chunking_version,
                    correlation_id=correlation_id or job.correlation_id,
                )
                self.session.commit()
            except Exception as exc:  # noqa: BLE001 - recorded per version
                self.session.rollback()
                failed += 1
                job = self._lock_job(job_id) or job
                job.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                self.session.commit()
                continue
            if rebuilt:
                processed += 1
            else:
                skipped += 1

        job = self._lock_job(job_id) or job
        job.processed_versions = processed
        job.skipped_versions = skipped
        job.failed_versions = failed
        job.finished_at = datetime.now(UTC)
        if failed:
            job.status = (
                "DEAD_LETTER" if job.attempt_count >= MAX_REINDEX_ATTEMPTS else "FAILED"
            )
        else:
            job.status = "SUCCEEDED"
        self.session.commit()
        self.session.refresh(job)
        return job

    def list_jobs(
        self,
        business_unit_id: str,
        *,
        limit: int = 20,
    ) -> list[KnowledgeReindexJob]:
        return list(
            self.session.scalars(
                select(KnowledgeReindexJob)
                .where(KnowledgeReindexJob.business_unit_id == business_unit_id)
                .order_by(KnowledgeReindexJob.created_at.desc())
                .limit(limit)
            ).all()
        )

    def get_job(self, job_id: UUID) -> KnowledgeReindexJob:
        job = self.session.get(KnowledgeReindexJob, job_id)
        if job is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Reindex job not found",
                detail=f"Reindex job {job_id} does not exist.",
            )
        return job

    def pending_version_count(self, business_unit_id: str | None) -> int:
        """Versions that still need a rebuild for the active model.

        Covers both an embedding-model switch and chunks written before the
        lexical channel existed (``lexical_text`` is NULL), so an upgrade is
        observable instead of silently degrading hybrid retrieval to dense.
        """
        missing_lexical_text = (
            select(KnowledgeChunk.id)
            .where(
                KnowledgeChunk.knowledge_version_id == KnowledgeVersion.id,
                KnowledgeChunk.lexical_text.is_(None),
            )
            .exists()
        )
        statement = (
            select(func.count())
            .select_from(KnowledgeVersion)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id,
            )
            .where(
                KnowledgeVersion.status != "FAILED",
                or_(
                    KnowledgeVersion.embedding_model != self.target_embedding_model,
                    missing_lexical_text,
                ),
            )
        )
        if business_unit_id:
            statement = statement.where(
                KnowledgeDocument.business_unit_id == business_unit_id
            )
        return self.session.scalar(statement) or 0

    def _lock_scope(self, business_unit_id: str, document_id: UUID | None) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        key = f"knowledge-reindex:{business_unit_id}:{document_id or '*'}"
        self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
            {"key": key},
        )

    def _active_job(
        self,
        business_unit_id: str,
        document_id: UUID | None,
    ) -> KnowledgeReindexJob | None:
        statement = select(KnowledgeReindexJob).where(
            KnowledgeReindexJob.business_unit_id == business_unit_id,
            KnowledgeReindexJob.status.in_(ACTIVE_STATUSES),
        )
        if document_id is None:
            statement = statement.where(KnowledgeReindexJob.document_id.is_(None))
        else:
            statement = statement.where(KnowledgeReindexJob.document_id == document_id)
        return self.session.scalars(
            statement.order_by(KnowledgeReindexJob.created_at.desc())
        ).first()

    def _lock_job(self, job_id: UUID) -> KnowledgeReindexJob | None:
        return self.session.scalar(
            select(KnowledgeReindexJob)
            .where(KnowledgeReindexJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _count_versions(
        self,
        business_unit_id: str,
        document_id: UUID | None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(KnowledgeVersion)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id,
            )
            .where(
                KnowledgeDocument.business_unit_id == business_unit_id,
                KnowledgeVersion.status != "FAILED",
            )
        )
        if document_id is not None:
            statement = statement.where(KnowledgeVersion.document_id == document_id)
        return self.session.scalar(statement) or 0

    def _version_ids(self, job: KnowledgeReindexJob) -> list[UUID]:
        statement = (
            select(KnowledgeVersion.id)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id,
            )
            .where(
                KnowledgeDocument.business_unit_id == job.business_unit_id,
                KnowledgeVersion.status != "FAILED",
            )
            .order_by(KnowledgeVersion.created_at)
        )
        if job.document_id is not None:
            statement = statement.where(KnowledgeVersion.document_id == job.document_id)
        return list(self.session.scalars(statement).all())

    def _version_is_current(
        self,
        version_id: UUID,
        job: KnowledgeReindexJob,
    ) -> bool:
        version = self.session.get(KnowledgeVersion, version_id)
        if version is None:
            return True
        if version.embedding_model != job.target_embedding_model:
            return False
        metadata_rows: list[dict[str, object] | None] = list(
            self.session.scalars(
                select(KnowledgeChunk.metadata_json).where(
                    KnowledgeChunk.knowledge_version_id == version_id
                )
            ).all()
        )
        if not metadata_rows:
            return False
        return all(
            (metadata or {}).get("chunking_version") == job.target_chunking_version
            and (metadata or {}).get("lexical_version") == LEXICAL_TOKENIZER_VERSION
            for metadata in metadata_rows
        )

    def _is_stale(self, job: KnowledgeReindexJob) -> bool:
        if job.started_at is None:
            return True
        started = job.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return datetime.now(UTC) - started > STALE_RUNNING_AFTER
