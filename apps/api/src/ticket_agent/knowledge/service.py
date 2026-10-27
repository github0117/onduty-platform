import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Float, bindparam, delete, func, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ticket_agent.audit.service import record_audit
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.knowledge.chunking import ChunkDraft, chunk_blocks
from ticket_agent.knowledge.document_parser import (
    DocumentParseError,
    parse_document,
    serialize_blocks,
)
from ticket_agent.knowledge.embedding_factory import get_embedding_provider
from ticket_agent.knowledge.embedding_types import (
    EmbeddingBatch,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from ticket_agent.knowledge.models import (
    DigitalEmployeeKnowledgeBinding,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEvaluationCase,
    KnowledgeSpace,
    KnowledgeVersion,
)
from ticket_agent.knowledge.rerank import Reranker, get_reranker
from ticket_agent.knowledge.retrieval import RetrievalCandidate
from ticket_agent.knowledge.schemas import (
    EmployeeKnowledgeBindingView,
    KnowledgeDocumentCreate,
    KnowledgeDocumentUpdate,
    KnowledgeDocumentView,
    KnowledgeSpaceCreate,
    KnowledgeSpaceUpdate,
    KnowledgeSpaceView,
    KnowledgeVersionCreate,
    KnowledgeVersionView,
)
from ticket_agent.knowledge.scope import scope_matches
from ticket_agent.knowledge.tokenizer import (
    LEXICAL_TOKENIZER_VERSION,
    build_lexical_text,
    build_tsquery,
)
from ticket_agent.model_gateway.usage import ModelUsageGuard
from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.settings import get_settings
from ticket_agent.storage.factory import get_object_storage
from ticket_agent.storage.types import ObjectStorage, ObjectStorageError
from ticket_agent.tickets.models import OutboxEvent


@dataclass(frozen=True)
class KnowledgeHit:
    chunk_id: UUID
    document_id: UUID
    title: str
    version: str
    content: str
    score: float
    space_id: UUID | None = None


class KnowledgeService:
    def __init__(
        self,
        session: Session,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.session = session
        self.settings = get_settings()
        self._uses_default_embedding_provider = embedding_provider is None
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.reranker = reranker or get_reranker()

    @property
    def retrieval_mode(self) -> str:
        """Effective retrieval channel set for this session's database.

        Hybrid retrieval needs PostgreSQL full-text search, so SQLite (used by
        unit tests and the offline demo) always degrades to dense retrieval.
        """
        if (
            self.settings.knowledge_retrieval_mode == "hybrid"
            and self.session.get_bind().dialect.name == "postgresql"
        ):
            return "hybrid"
        return "dense"

    def create_space(self, payload: KnowledgeSpaceCreate) -> KnowledgeSpace:
        existing = self.session.scalar(
            select(KnowledgeSpace).where(
                KnowledgeSpace.business_unit_id == payload.business_unit_id,
                KnowledgeSpace.code == payload.code,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_SPACE_EXISTS",
                title="Knowledge space already exists",
                detail="code must be unique within the business unit.",
            )
        space = KnowledgeSpace(
            business_unit_id=payload.business_unit_id,
            code=payload.code,
            name=payload.name.strip(),
            description=payload.description.strip(),
            domain=payload.domain.strip(),
            channel=payload.channel,
            category=payload.category,
            category_profile_id=payload.category_profile_id,
            workflow_key=payload.workflow_key,
            owner_id=payload.owner_id,
            evaluation_required=payload.evaluation_required,
            status="ACTIVE",
        )
        self.session.add(space)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_SPACE_EXISTS",
                title="Knowledge space already exists",
                detail="code must be unique within the business unit.",
            ) from exc
        self.session.refresh(space)
        return space

    def update_space(
        self,
        space_id: UUID,
        payload: KnowledgeSpaceUpdate,
        *,
        actor_id: str,
    ) -> KnowledgeSpace:
        space = self._get_space(space_id)
        for field in (
            "name",
            "description",
            "domain",
            "channel",
            "category",
            "category_profile_id",
            "workflow_key",
            "owner_id",
            "evaluation_required",
            "status",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(space, field, value.strip() if isinstance(value, str) else value)
        if space.status == "DISABLED":
            self.session.execute(
                update(KnowledgeEvaluationCase)
                .where(
                    KnowledgeEvaluationCase.knowledge_space_id == space.id,
                    KnowledgeEvaluationCase.enabled.is_(True),
                )
                .values(enabled=False)
            )
        self.session.flush()
        employee_ids = set(
            self.session.scalars(
                select(DigitalEmployeeKnowledgeBinding.employee_id).where(
                    DigitalEmployeeKnowledgeBinding.knowledge_space_id
                    == space.id,
                    DigitalEmployeeKnowledgeBinding.enabled.is_(True),
                )
            ).all()
        )
        from ticket_agent.digital_employees.service import (
            DigitalEmployeeService,
        )

        employee_service = DigitalEmployeeService(self.session)
        for employee_id in employee_ids:
            employee_service.invalidate_activation_if_changed(
                employee_service.get_for_update(employee_id),
                actor_id=actor_id,
                note=(
                    f"Knowledge space {space.code} changed; "
                    "employee reactivation required"
                ),
                require_baseline=True,
            )
        self.session.commit()
        self.session.refresh(space)
        return space

    def get_space(self, space_id: UUID) -> KnowledgeSpace:
        return self._get_space(space_id)

    def list_spaces(self, business_unit_id: str | None) -> list[KnowledgeSpace]:
        statement = select(KnowledgeSpace).order_by(
            KnowledgeSpace.business_unit_id,
            KnowledgeSpace.name,
        )
        if business_unit_id:
            statement = statement.where(
                KnowledgeSpace.business_unit_id == business_unit_id
            )
        return list(self.session.scalars(statement).all())

    def replace_employee_bindings(
        self,
        employee_id: UUID,
        *,
        bindings: list[dict[str, object]],
        commit: bool = True,
        actor_id: str = "system.knowledge_binding",
    ) -> list[DigitalEmployeeKnowledgeBinding]:
        from ticket_agent.digital_employees.service import (
            DigitalEmployeeService,
        )

        employee_service = DigitalEmployeeService(self.session)
        employee = employee_service.get_for_update(employee_id)
        binding_keys = [
            (
                cast(UUID, binding["knowledge_space_id"]),
                cast(str | None, binding.get("workflow_key")),
            )
            for binding in bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ApiProblem(
                status_code=422,
                code="KNOWLEDGE_BINDING_DUPLICATED",
                title="Duplicate knowledge binding",
                detail=(
                    "Each knowledge space and workflow pair can appear "
                    "only once."
                ),
            )
        space_ids = {space_id for space_id, _workflow in binding_keys}
        spaces = self.session.scalars(
            select(KnowledgeSpace).where(KnowledgeSpace.id.in_(space_ids))
        ).all()
        if len(spaces) != len(space_ids):
            raise ApiProblem(
                status_code=404,
                code="KNOWLEDGE_SPACE_NOT_FOUND",
                title="Knowledge space not found",
                detail="One or more knowledge spaces do not exist.",
            )
        if any(
            space.business_unit_id != employee.business_unit_id for space in spaces
        ):
            raise ApiProblem(
                status_code=422,
                code="KNOWLEDGE_SPACE_UNIT_MISMATCH",
                title="Knowledge space belongs to another business unit",
                detail="An employee can only bind knowledge from its own business unit.",
            )

        existing = self.session.scalars(
            select(DigitalEmployeeKnowledgeBinding).where(
                DigitalEmployeeKnowledgeBinding.employee_id == employee_id
            )
        ).all()
        for existing_binding in existing:
            self.session.delete(existing_binding)
        self.session.flush()

        created: list[DigitalEmployeeKnowledgeBinding] = []
        for binding_data in bindings:
            record = DigitalEmployeeKnowledgeBinding(
                employee_id=employee_id,
                knowledge_space_id=cast(UUID, binding_data["knowledge_space_id"]),
                workflow_key=cast(str | None, binding_data.get("workflow_key")),
                scope_json=cast(dict[str, Any], binding_data.get("scope") or {}),
                enabled=bool(binding_data.get("enabled", True)),
            )
            self.session.add(record)
            created.append(record)
        self.session.flush()
        if commit:
            employee_service.invalidate_activation_if_changed(
                employee,
                actor_id=actor_id,
                note=(
                    "Employee knowledge bindings changed; "
                    "reactivation required"
                ),
            )
            self.session.commit()
        for record in created:
            self.session.refresh(record)
        return created

    def list_employee_bindings(
        self,
        employee_id: UUID,
    ) -> list[DigitalEmployeeKnowledgeBinding]:
        if self.session.get(DigitalEmployee, employee_id) is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Digital employee not found",
                detail=f"Digital employee {employee_id} does not exist.",
            )
        return list(
            self.session.scalars(
                select(DigitalEmployeeKnowledgeBinding)
                .where(DigitalEmployeeKnowledgeBinding.employee_id == employee_id)
                .order_by(DigitalEmployeeKnowledgeBinding.created_at)
            ).all()
        )

    def space_view(self, space: KnowledgeSpace) -> KnowledgeSpaceView:
        document_count = self.session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.space_id == space.id)
        ) or 0
        return KnowledgeSpaceView(
            id=space.id,
            business_unit_id=space.business_unit_id,
            code=space.code,
            name=space.name,
            description=space.description,
            domain=space.domain,
            channel=space.channel,
            category=space.category,
            category_profile_id=space.category_profile_id,
            workflow_key=space.workflow_key,
            owner_id=space.owner_id,
            evaluation_required=space.evaluation_required,
            status=space.status,
            document_count=document_count,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )

    def binding_view(
        self,
        binding: DigitalEmployeeKnowledgeBinding,
    ) -> EmployeeKnowledgeBindingView:
        return EmployeeKnowledgeBindingView(
            id=binding.id,
            employee_id=binding.employee_id,
            knowledge_space_id=binding.knowledge_space_id,
            workflow_key=binding.workflow_key,
            scope=binding.scope_json,
            enabled=binding.enabled,
            created_at=binding.created_at,
            updated_at=binding.updated_at,
        )

    def create_document(
        self,
        payload: KnowledgeDocumentCreate,
        *,
        actor_id: str,
    ) -> KnowledgeDocument:
        space = self._validate_document_space(
            payload.space_id,
            business_unit_id=payload.business_unit_id,
        )
        document = KnowledgeDocument(
            space_id=space.id if space else None,
            business_unit_id=payload.business_unit_id,
            title=payload.title.strip(),
            doc_type=payload.doc_type,
            owner_id=payload.owner_id,
            scope_json=payload.scope,
            status="DRAFT",
        )
        self.session.add(document)
        self.session.flush()
        return document

    def create_version(
        self,
        document_id: UUID,
        payload: KnowledgeVersionCreate,
        *,
        source_filename: str | None = None,
        source_mime_type: str | None = None,
        source_size_bytes: int | None = None,
        source_object_key: str | None = None,
        parser_name: str | None = None,
        parser_version: str | None = None,
        content_blocks: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> KnowledgeVersion:
        document = self._get_document(document_id)
        self._ensure_embedding_usage_scope(
            business_unit_id=document.business_unit_id,
            correlation_id=correlation_id,
        )
        if payload.effective_to and payload.effective_to <= payload.effective_from:
            raise ApiProblem(
                status_code=422,
                code="SCHEMA_VALIDATION_FAILED",
                title="Invalid effective period",
                detail="effective_to must be later than effective_from.",
            )

        version = KnowledgeVersion(
            document_id=document.id,
            version_label=payload.version_label,
            status="DRAFT",
            content_text=payload.content,
            content_hash=hashlib.sha256(payload.content.encode("utf-8")).hexdigest(),
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            embedding_model=self.embedding_provider.name,
            source_filename=source_filename,
            source_mime_type=source_mime_type,
            source_size_bytes=source_size_bytes,
            source_object_key=source_object_key,
            parser_name=parser_name,
            parser_version=parser_version,
            content_blocks_json=content_blocks,
        )
        self.session.add(version)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_VERSION_EXISTS",
                title="Knowledge version already exists",
                detail=f"Version {payload.version_label} already exists for this document.",
            ) from exc

        self._add_chunks(
            version,
            document,
            payload.content,
            correlation_id=correlation_id,
            content_blocks=content_blocks,
        )
        self.session.commit()
        self.session.refresh(version)
        return version

    def update_document(
        self,
        document_id: UUID,
        payload: KnowledgeDocumentUpdate,
    ) -> KnowledgeDocument:
        document = self._get_document(document_id)
        if document.status == "ARCHIVED":
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_DOCUMENT_ARCHIVED",
                title="Knowledge document is archived",
                detail="Archived documents cannot be edited.",
            )
        if payload.space_id is not None:
            space = self._validate_document_space(
                payload.space_id,
                business_unit_id=document.business_unit_id,
            )
            document.space_id = space.id if space else None
        if payload.title is not None:
            document.title = payload.title.strip()
        if payload.doc_type is not None:
            document.doc_type = payload.doc_type
        if payload.owner_id is not None:
            document.owner_id = payload.owner_id
        if payload.scope is not None:
            document.scope_json = payload.scope
        self.session.commit()
        self.session.refresh(document)
        return document

    def archive_document(self, document_id: UUID) -> KnowledgeDocument:
        document = self._get_document(document_id)
        if document.status == "ARCHIVED":
            return document
        document.status = "ARCHIVED"
        versions = self.session.scalars(
            select(KnowledgeVersion).where(
                KnowledgeVersion.document_id == document.id,
                KnowledgeVersion.status.in_(["ACTIVE", "DRAFT"]),
            )
        ).all()
        for version in versions:
            version.status = "RETIRED"
        self.session.commit()
        self.session.refresh(document)
        return document

    def restore_document(self, document_id: UUID) -> KnowledgeDocument:
        document = self._get_document(document_id)
        if document.status == "ACTIVE":
            return document
        current_version = (
            self.session.get(KnowledgeVersion, document.current_version_id)
            if document.current_version_id
            else None
        )
        if current_version is None or current_version.status != "RETIRED":
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_DOCUMENT_NO_RESTORABLE_VERSION",
                title="Knowledge document has no restorable version",
                detail=(
                    "The document has no retired current version that can be "
                    "restored."
                ),
            )
        current_version.status = "ACTIVE"
        document.status = "ACTIVE"
        self.session.commit()
        self.session.refresh(document)
        return document

    def create_version_from_file(
        self,
        document_id: UUID,
        *,
        version_label: str,
        filename: str,
        content_type: str,
        data: bytes,
        correlation_id: str | None = None,
    ) -> KnowledgeVersion:
        try:
            parsed = parse_document(
                filename=filename,
                content_type=content_type,
                data=data,
                max_bytes=self.settings.knowledge_max_file_bytes,
            )
        except DocumentParseError as exc:
            raise ApiProblem(
                status_code=415 if exc.code == "UNSUPPORTED_DOCUMENT_TYPE" else 422,
                code=exc.code,
                title="Document parsing failed",
                detail=str(exc),
            ) from exc

        return self.create_version(
            document_id,
            KnowledgeVersionCreate(
                version_label=version_label,
                content=parsed.text,
            ),
            source_filename=filename,
            source_mime_type=content_type or "application/octet-stream",
            source_size_bytes=len(data),
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            content_blocks=serialize_blocks(parsed.blocks, parsed.warnings),
            correlation_id=correlation_id,
        )

    def create_async_upload(
        self,
        document_id: UUID,
        *,
        version_label: str,
        filename: str,
        content_type: str,
        data: bytes,
        correlation_id: str,
        storage: ObjectStorage | None = None,
    ) -> tuple[KnowledgeVersion, UUID]:
        document = self._get_document(document_id)
        self._ensure_embedding_usage_scope(
            business_unit_id=document.business_unit_id,
            correlation_id=correlation_id,
        )
        if len(data) > self.settings.knowledge_max_file_bytes:
            raise ApiProblem(
                status_code=422,
                code="FILE_TOO_LARGE",
                title="Document is too large",
                detail=(
                    f"Document exceeds the {self.settings.knowledge_max_file_bytes} byte limit."
                ),
            )
        if not data:
            raise ApiProblem(
                status_code=422,
                code="EMPTY_FILE",
                title="Document is empty",
                detail="Document is empty.",
            )

        storage = storage or get_object_storage()
        mime_type = content_type or "application/octet-stream"
        version = KnowledgeVersion(
            document_id=document.id,
            version_label=version_label,
            status="PROCESSING",
            content_text="",
            content_hash=hashlib.sha256(data).hexdigest(),
            effective_from=datetime.now(UTC),
            embedding_model=self.embedding_provider.name,
            source_filename=Path(filename).name,
            source_mime_type=mime_type,
            source_size_bytes=len(data),
            processing_started_at=datetime.now(UTC),
        )
        self.session.add(version)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_VERSION_EXISTS",
                title="Knowledge version already exists",
                detail=f"Version {version_label} already exists for this document.",
            ) from exc

        object_key = (
            f"knowledge/{document.business_unit_id}/{document.id}/"
            f"{version.id}/{version.source_filename}"
        )
        try:
            storage.put_object(
                key=object_key,
                data=data,
                content_type=mime_type,
            )
        except ObjectStorageError as exc:
            self.session.rollback()
            raise ApiProblem(
                status_code=503,
                code="OBJECT_STORAGE_UNAVAILABLE",
                title="Object storage is unavailable",
                detail="Unable to persist the uploaded file.",
                retryable=True,
            ) from exc
        version.source_object_key = object_key
        outbox_event = OutboxEvent(
            aggregate_type="knowledge_version",
            aggregate_id=version.id,
            event_type="knowledge.version.ingest",
            payload_json={
                "version_id": str(version.id),
                "document_id": str(document.id),
                "correlation_id": correlation_id,
            },
        )
        self.session.add(outbox_event)
        self.session.commit()
        self.session.refresh(version)
        return version, outbox_event.id

    def ingest_stored_version(
        self,
        version_id: UUID,
        *,
        correlation_id: str,
        storage: ObjectStorage | None = None,
    ) -> KnowledgeVersion:
        version = self.session.scalar(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.id == version_id)
            .with_for_update()
        )
        if version is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge version not found",
                detail=f"Knowledge version {version_id} does not exist.",
            )
        if version.status != "PROCESSING":
            return version
        document = self._get_document(version.document_id)
        if not version.source_object_key or not version.source_filename:
            self._fail_ingestion(version, "SOURCE_OBJECT_MISSING")
            return version

        storage = storage or get_object_storage()
        try:
            data = storage.get_object(key=version.source_object_key)
            parsed = parse_document(
                filename=version.source_filename,
                content_type=version.source_mime_type or "application/octet-stream",
                data=data,
                max_bytes=self.settings.knowledge_max_file_bytes,
            )
        except (ObjectStorageError, DocumentParseError) as exc:
            self._fail_ingestion(version, str(exc))
            return version

        version.content_text = parsed.text
        version.content_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
        version.parser_name = parsed.parser_name
        version.parser_version = parsed.parser_version
        version.content_blocks_json = serialize_blocks(parsed.blocks, parsed.warnings)
        version.ingestion_error = None
        version.processed_at = datetime.now(UTC)
        try:
            self._add_chunks(
                version,
                document,
                parsed.text,
                correlation_id=correlation_id,
                content_blocks=version.content_blocks_json,
            )
        except ApiProblem as exc:
            self._fail_ingestion(version, exc.code)
            return version
        version.status = "DRAFT"
        record_audit(
            self.session,
            correlation_id=correlation_id,
            event_type="knowledge.version.ingested",
            actor_type="SERVICE",
            actor_id="digital_agent.ticket.v1",
            resource_type="knowledge_version",
            resource_id=version.id,
            action="ingest",
            decision="EXECUTED",
            payload={
                "document_id": str(document.id),
                "version_label": version.version_label,
                "parser_name": version.parser_name,
                "source_size_bytes": version.source_size_bytes,
            },
        )
        self.session.commit()
        self.session.refresh(version)
        return version

    def get_version(self, document_id: UUID, version_id: UUID) -> KnowledgeVersion:
        version = self.session.scalar(
            select(KnowledgeVersion).where(
                KnowledgeVersion.id == version_id,
                KnowledgeVersion.document_id == document_id,
            )
        )
        if version is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge version not found",
                detail=f"Knowledge version {version_id} does not exist.",
            )
        return version

    def publish_version(
        self,
        document_id: UUID,
        version_id: UUID,
        *,
        actor_id: str,
    ) -> KnowledgeVersion:
        document = self._get_document(document_id)
        version = self.session.scalar(
            select(KnowledgeVersion)
            .where(
                KnowledgeVersion.id == version_id,
                KnowledgeVersion.document_id == document_id,
            )
            .with_for_update()
        )
        if version is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge version not found",
                detail=f"Knowledge version {version_id} does not exist.",
            )
        if version.status != "DRAFT":
            raise ApiProblem(
                status_code=409,
                code="INVALID_KNOWLEDGE_STATE",
                title="Knowledge version cannot be published",
                detail=f"Knowledge version is in {version.status} state.",
            )

        chunk_count = self.session.scalar(
            select(KnowledgeChunk.id)
            .where(KnowledgeChunk.knowledge_version_id == version.id)
            .limit(1)
        )
        if chunk_count is None:
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_VERSION_EMPTY",
                title="Knowledge version has no chunks",
                detail="The document must be ingested before publishing.",
            )

        now = datetime.now(UTC)
        if _as_utc(version.effective_from) <= now:
            previous_versions = self.session.scalars(
                select(KnowledgeVersion)
                .where(
                    KnowledgeVersion.document_id == document.id,
                    KnowledgeVersion.status == "ACTIVE",
                    KnowledgeVersion.id != version.id,
                )
                .with_for_update()
            ).all()
            for previous in previous_versions:
                previous.status = "SUPERSEDED"
                previous.effective_to = version.effective_from

        version.status = "ACTIVE"
        version.published_at = now
        version.published_by = actor_id
        document.status = "ACTIVE"
        document.current_version_id = version.id
        self.session.commit()
        self.session.refresh(version)
        return version

    def list_documents(
        self,
        business_unit_id: str,
        space_id: UUID | None = None,
    ) -> list[KnowledgeDocument]:
        statement = select(KnowledgeDocument).where(
            KnowledgeDocument.business_unit_id == business_unit_id
        )
        if space_id:
            statement = statement.where(KnowledgeDocument.space_id == space_id)
        return list(
            self.session.scalars(
                statement.order_by(KnowledgeDocument.updated_at.desc())
            ).all()
        )

    def list_versions(self, document_id: UUID) -> list[KnowledgeVersion]:
        self._get_document(document_id)
        return list(
            self.session.scalars(
                select(KnowledgeVersion)
                .where(KnowledgeVersion.document_id == document_id)
                .order_by(KnowledgeVersion.created_at.desc())
            ).all()
        )

    def search(
        self,
        *,
        query: str,
        business_unit_id: str,
        space_id: UUID | None = None,
        employee_id: UUID | None = None,
        scope: dict[str, str] | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
        correlation_id: str | None = None,
    ) -> list[KnowledgeHit]:
        search_scope = self._resolve_search_scope(
            business_unit_id=business_unit_id,
            space_id=space_id,
            employee_id=employee_id,
            scope=scope,
        )
        version_rows = self._effective_versions(
            business_unit_id,
            search_scope,
            space_id=space_id,
            employee_id=employee_id,
        )
        if not version_rows:
            return []
        self._ensure_embedding_usage_scope(
            business_unit_id=business_unit_id,
            correlation_id=correlation_id,
        )
        version_ids = [version.id for version, document in version_rows]
        query_vector = self.embedding_provider.embed_texts([query])[0]
        limit = top_k or self.settings.knowledge_search_top_k
        candidate_limit = limit * self.settings.knowledge_candidate_multiplier
        dialect = self.session.get_bind().dialect.name

        dense_candidates = self._dense_candidates(
            query_vector,
            version_ids,
            limit=candidate_limit,
            dialect=dialect,
        )
        if self.retrieval_mode == "hybrid":
            lexical_candidates = self._lexical_candidates(
                query=query,
                query_vector=query_vector,
                version_ids=version_ids,
                limit=candidate_limit,
            )
            candidates = _rrf_fuse(
                [dense_candidates, lexical_candidates],
                limit=candidate_limit,
                k=self.settings.knowledge_rrf_k,
            )
        else:
            candidates = dense_candidates

        ranked = self.reranker.rerank(query=query, candidates=candidates, top_k=limit)
        hits: list[KnowledgeHit] = []
        score_threshold = (
            min_score
            if min_score is not None
            else self.settings.knowledge_min_score
        )
        for ranked_candidate in ranked:
            if ranked_candidate.final_score < score_threshold:
                continue
            candidate = ranked_candidate.candidate
            hits.append(
                KnowledgeHit(
                    chunk_id=candidate.chunk_id,
                    document_id=candidate.document_id,
                    space_id=candidate.space_id,
                    title=candidate.title,
                    version=candidate.version,
                    content=candidate.content,
                    score=ranked_candidate.final_score,
                )
            )
        return hits

    def _dense_candidates(
        self,
        query_vector: list[float],
        version_ids: list[UUID],
        *,
        limit: int,
        dialect: str,
    ) -> list[RetrievalCandidate]:
        if dialect == "postgresql":
            distance = sql_cast(
                KnowledgeChunk.embedding.op("<=>")(
                    bindparam(
                        "query_embedding",
                        query_vector,
                        type_=KnowledgeChunk.embedding.type,
                    )
                ),
                Float,
            ).label("distance")
            rows = self.session.execute(
                select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument, distance)
                .join(
                    KnowledgeVersion,
                    KnowledgeVersion.id == KnowledgeChunk.knowledge_version_id,
                )
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id == KnowledgeVersion.document_id,
                )
                .where(
                    KnowledgeChunk.knowledge_version_id.in_(version_ids),
                    KnowledgeVersion.embedding_model == self.embedding_provider.name,
                )
                .order_by(distance)
                .limit(limit)
            ).all()
            return [
                _retrieval_candidate(row, vector_score=1.0 - float(row[3]))
                for row in rows
            ]
        sqlite_rows = self.session.execute(
            select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument)
            .join(
                KnowledgeVersion,
                KnowledgeVersion.id == KnowledgeChunk.knowledge_version_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id,
            )
            .where(
                KnowledgeChunk.knowledge_version_id.in_(version_ids),
                KnowledgeVersion.embedding_model == self.embedding_provider.name,
            )
        ).all()
        return [
            _retrieval_candidate(
                row,
                vector_score=_cosine_similarity(query_vector, row[0].embedding),
            )
            for row in sqlite_rows
        ]

    def _lexical_candidates(
        self,
        *,
        query: str,
        query_vector: list[float],
        version_ids: list[UUID],
        limit: int,
    ) -> list[RetrievalCandidate]:
        tsquery_text = build_tsquery(query)
        if not tsquery_text:
            return []
        # Keep this expression identical to the GIN index expression so the
        # planner can use ix_knowledge_chunks_lexical.
        document_vector = func.to_tsvector(
            sql_text("'simple'"),
            func.coalesce(KnowledgeChunk.lexical_text, ""),
        )
        tsquery = func.to_tsquery(
            sql_text("'simple'"),
            bindparam("lexical_query", tsquery_text),
        )
        rank = func.ts_rank_cd(document_vector, tsquery).label("rank")
        rows = self.session.execute(
            select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument, rank)
            .join(
                KnowledgeVersion,
                KnowledgeVersion.id == KnowledgeChunk.knowledge_version_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeVersion.document_id,
            )
            .where(
                KnowledgeChunk.knowledge_version_id.in_(version_ids),
                KnowledgeVersion.embedding_model == self.embedding_provider.name,
                document_vector.op("@@")(tsquery),
            )
            .order_by(rank.desc())
            .limit(limit)
        ).all()
        return [
            _retrieval_candidate(
                row,
                vector_score=_cosine_similarity(query_vector, row[0].embedding),
            )
            for row in rows
        ]

    def _resolve_search_scope(
        self,
        *,
        business_unit_id: str,
        space_id: UUID | None,
        employee_id: UUID | None,
        scope: dict[str, str] | None,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        if employee_id is not None:
            employee = self.session.get(DigitalEmployee, employee_id)
            if employee is None:
                raise ApiProblem(
                    status_code=404,
                    code="RESOURCE_NOT_FOUND",
                    title="Digital employee not found",
                    detail=f"Digital employee {employee_id} does not exist.",
                )
            if employee.business_unit_id != business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="KNOWLEDGE_EMPLOYEE_UNIT_MISMATCH",
                    title="Employee belongs to another business unit",
                    detail="The employee cannot retrieve this business unit's knowledge.",
                )
            default_scope = employee.knowledge_policy_json.get("default_scope", {})
            if isinstance(default_scope, dict):
                resolved.update(
                    {
                        str(key): value
                        for key, value in default_scope.items()
                        if isinstance(value, str)
                    }
                )
        if space_id is not None:
            space = self._get_space(space_id)
            for key, value in (
                ("channel", space.channel),
                ("category", space.category),
                ("workflow", space.workflow_key),
            ):
                if value and key not in resolved:
                    resolved[key] = value
        if scope:
            resolved.update(scope)
        return resolved

    def version_view(self, version: KnowledgeVersion) -> KnowledgeVersionView:
        count = len(
            self.session.scalars(
                select(KnowledgeChunk.id).where(
                    KnowledgeChunk.knowledge_version_id == version.id
                )
            ).all()
        )
        return KnowledgeVersionView(
            id=version.id,
            document_id=version.document_id,
            version_label=version.version_label,
            status=version.status,
            content_hash=version.content_hash,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
            embedding_model=version.embedding_model,
            source_filename=version.source_filename,
            source_mime_type=version.source_mime_type,
            source_size_bytes=version.source_size_bytes,
            source_object_key=version.source_object_key,
            parser_name=version.parser_name,
            parser_version=version.parser_version,
            ingestion_error=version.ingestion_error,
            processing_started_at=version.processing_started_at,
            processed_at=version.processed_at,
            chunk_count=count,
            published_at=version.published_at,
            created_at=version.created_at,
        )

    def document_view(self, document: KnowledgeDocument) -> KnowledgeDocumentView:
        return KnowledgeDocumentView(
            id=document.id,
            space_id=document.space_id,
            business_unit_id=document.business_unit_id,
            title=document.title,
            doc_type=document.doc_type,
            owner_id=document.owner_id,
            scope=document.scope_json,
            source_type=document.source_type,
            source_ref=document.source_ref,
            source_version=document.source_version,
            sync_status=document.sync_status,
            last_synced_at=document.last_synced_at,
            status=document.status,
            current_version_id=document.current_version_id,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )

    def get_document(self, document_id: UUID) -> KnowledgeDocument:
        return self._get_document(document_id)

    def _get_document(self, document_id: UUID) -> KnowledgeDocument:
        document = self.session.get(KnowledgeDocument, document_id)
        if document is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge document not found",
                detail=f"Knowledge document {document_id} does not exist.",
            )
        return document

    def _effective_versions(
        self,
        business_unit_id: str,
        scope: dict[str, str] | None,
        *,
        space_id: UUID | None = None,
        employee_id: UUID | None = None,
    ) -> list[tuple[KnowledgeVersion, KnowledgeDocument]]:
        allowed_space_ids = self._allowed_space_ids(
            business_unit_id=business_unit_id,
            space_id=space_id,
            employee_id=employee_id,
            scope=scope,
        )
        if allowed_space_ids is not None and not allowed_space_ids:
            return []
        now = datetime.now(UTC)
        statement = (
            select(KnowledgeVersion, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
            .where(
                KnowledgeDocument.business_unit_id == business_unit_id,
                KnowledgeDocument.status == "ACTIVE",
                KnowledgeVersion.status == "ACTIVE",
                KnowledgeVersion.effective_from <= now,
                (KnowledgeVersion.effective_to.is_(None))
                | (KnowledgeVersion.effective_to > now),
                KnowledgeVersion.embedding_model == self.embedding_provider.name,
            )
            .order_by(KnowledgeVersion.effective_from.desc())
        )
        if allowed_space_ids is not None:
            statement = statement.where(
                KnowledgeDocument.space_id.in_(allowed_space_ids)
            )
        else:
            active_space_ids = select(KnowledgeSpace.id).where(
                KnowledgeSpace.business_unit_id == business_unit_id,
                KnowledgeSpace.status == "ACTIVE",
            )
            statement = statement.where(
                KnowledgeDocument.space_id.is_(None)
                | KnowledgeDocument.space_id.in_(active_space_ids)
            )
        rows = self.session.execute(statement).all()

        latest_by_document: dict[UUID, tuple[KnowledgeVersion, KnowledgeDocument]] = {}
        for version, document in rows:
            if not scope_matches(document.scope_json, scope):
                continue
            latest_by_document.setdefault(document.id, (version, document))
        return list(latest_by_document.values())

    def _allowed_space_ids(
        self,
        *,
        business_unit_id: str,
        space_id: UUID | None,
        employee_id: UUID | None,
        scope: dict[str, str] | None,
    ) -> set[UUID] | None:
        explicit_space_ids: set[UUID] | None = None
        if space_id is not None:
            space = self._get_space(space_id)
            if space.business_unit_id != business_unit_id:
                raise ApiProblem(
                    status_code=422,
                    code="KNOWLEDGE_SPACE_UNIT_MISMATCH",
                    title="Knowledge space belongs to another business unit",
                    detail="The requested knowledge space is outside the business unit.",
                )
            explicit_space_ids = {space.id} if space.status == "ACTIVE" else set()

        if employee_id is None:
            return explicit_space_ids

        employee = self.session.get(DigitalEmployee, employee_id)
        if employee is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Digital employee not found",
                detail=f"Digital employee {employee_id} does not exist.",
            )
        if employee.business_unit_id != business_unit_id:
            raise ApiProblem(
                status_code=422,
                code="KNOWLEDGE_EMPLOYEE_UNIT_MISMATCH",
                title="Employee belongs to another business unit",
                detail="The employee cannot retrieve this business unit's knowledge.",
            )
        if employee.status != "ACTIVE":
            return set()
        requested_workflow = (scope or {}).get("workflow")
        bindings = self.session.scalars(
            select(DigitalEmployeeKnowledgeBinding).where(
                DigitalEmployeeKnowledgeBinding.employee_id == employee_id,
                DigitalEmployeeKnowledgeBinding.enabled.is_(True),
            )
        ).all()
        if not bindings:
            has_active_spaces = self.session.scalar(
                select(func.count())
                .select_from(KnowledgeSpace)
                .where(
                    KnowledgeSpace.business_unit_id == business_unit_id,
                    KnowledgeSpace.status == "ACTIVE",
                )
            )
            if explicit_space_ids is None and not has_active_spaces:
                return None
            return set()
        bound_space_ids = {
            binding.knowledge_space_id
            for binding in bindings
            if (
                requested_workflow is None
                or binding.workflow_key in {None, requested_workflow}
            )
            and scope_matches(binding.scope_json, scope)
        }
        active_space_ids = set(
            self.session.scalars(
                select(KnowledgeSpace.id).where(
                    KnowledgeSpace.id.in_(bound_space_ids),
                    KnowledgeSpace.status == "ACTIVE",
                )
            ).all()
        )
        if explicit_space_ids is None:
            return active_space_ids
        return explicit_space_ids & active_space_ids

    def _get_space(self, space_id: UUID) -> KnowledgeSpace:
        space = self.session.get(KnowledgeSpace, space_id)
        if space is None:
            raise ApiProblem(
                status_code=404,
                code="RESOURCE_NOT_FOUND",
                title="Knowledge space not found",
                detail=f"Knowledge space {space_id} does not exist.",
            )
        return space

    def _validate_document_space(
        self,
        space_id: UUID | None,
        *,
        business_unit_id: str,
    ) -> KnowledgeSpace | None:
        if space_id is None:
            return None
        space = self._get_space(space_id)
        if space.business_unit_id != business_unit_id:
            raise ApiProblem(
                status_code=422,
                code="KNOWLEDGE_SPACE_UNIT_MISMATCH",
                title="Knowledge space belongs to another business unit",
                detail="A document must use a knowledge space from its business unit.",
            )
        if space.status != "ACTIVE":
            raise ApiProblem(
                status_code=409,
                code="KNOWLEDGE_SPACE_DISABLED",
                title="Knowledge space is disabled",
                detail="Disabled knowledge spaces cannot receive documents.",
            )
        return space

    def _chunk_text(self, text: str) -> list[str]:
        size = self.settings.knowledge_chunk_size
        overlap = min(self.settings.knowledge_chunk_overlap, size // 2)
        normalized = text.replace("\r\n", "\n").strip()
        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            proposed_end = min(len(normalized), start + size)
            end = proposed_end
            if proposed_end < len(normalized):
                boundary = max(
                    normalized.rfind("\n", start + size // 2, proposed_end),
                    normalized.rfind("。", start + size // 2, proposed_end),
                    normalized.rfind("；", start + size // 2, proposed_end),
                )
                if boundary > start:
                    end = boundary + 1
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(start + 1, end - overlap)
        return chunks or [normalized]

    def _add_chunks(
        self,
        version: KnowledgeVersion,
        document: KnowledgeDocument,
        content: str,
        *,
        correlation_id: str | None = None,
        content_blocks: dict[str, Any] | None = None,
        chunking_version: str | None = None,
    ) -> None:
        self._ensure_embedding_usage_scope(
            business_unit_id=document.business_unit_id,
            correlation_id=correlation_id,
        )
        resolved_chunking_version = self._resolve_chunking_version(
            content_blocks,
            chunking_version,
        )
        drafts = self._chunk_drafts(
            content,
            content_blocks,
            chunking_version=resolved_chunking_version,
        )
        batch = self._embed_drafts(drafts)
        self._write_chunks(
            version,
            document,
            drafts,
            batch,
            chunking_version=resolved_chunking_version,
        )
        version.embedding_model = batch.model_name
        version.embedding_indexed_at = datetime.now(UTC)

    def rebuild_version_chunks(
        self,
        version_id: UUID,
        *,
        chunking_version: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Rebuild chunks for one version without touching object storage."""
        version = self.session.scalar(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.id == version_id)
            .with_for_update()
        )
        if version is None:
            return False
        document = self.session.get(KnowledgeDocument, version.document_id)
        if document is None or not version.content_text.strip():
            return False
        self._ensure_embedding_usage_scope(
            business_unit_id=document.business_unit_id,
            correlation_id=correlation_id,
        )
        resolved_chunking_version = self._resolve_chunking_version(
            version.content_blocks_json,
            chunking_version,
        )
        drafts = self._chunk_drafts(
            version.content_text,
            version.content_blocks_json,
            chunking_version=resolved_chunking_version,
        )
        if not drafts:
            return False
        batch = self._embed_drafts(drafts)
        self.session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.knowledge_version_id == version.id
            )
        )
        self._write_chunks(
            version,
            document,
            drafts,
            batch,
            chunking_version=resolved_chunking_version,
        )
        version.embedding_model = batch.model_name
        version.embedding_indexed_at = datetime.now(UTC)
        self.session.flush()
        return True

    def _embed_drafts(self, drafts: list[ChunkDraft]) -> EmbeddingBatch:
        try:
            batch = self.embedding_provider.embed(
                [draft.embedding_text for draft in drafts]
            )
        except EmbeddingProviderError as exc:
            raise ApiProblem(
                status_code=503,
                code="EMBEDDING_UNAVAILABLE",
                title="Embedding provider is unavailable",
                detail="Embedding generation failed; no vectors were stored.",
                retryable=True,
            ) from exc
        if len(batch.vectors) != len(drafts):
            raise ApiProblem(
                status_code=503,
                code="EMBEDDING_UNAVAILABLE",
                title="Embedding provider is unavailable",
                detail="Embedding count does not match the chunk count.",
                retryable=True,
            )
        return batch

    def _write_chunks(
        self,
        version: KnowledgeVersion,
        document: KnowledgeDocument,
        drafts: list[ChunkDraft],
        batch: EmbeddingBatch,
        *,
        chunking_version: str,
    ) -> None:
        for ordinal, (draft, embedding) in enumerate(
            zip(drafts, batch.vectors, strict=True)
        ):
            metadata: dict[str, Any] = {
                "title": document.title,
                "ordinal": ordinal,
                "chunking_version": chunking_version,
                "embedding_model": batch.model_name,
                "lexical_version": LEXICAL_TOKENIZER_VERSION,
            }
            if batch.fallback_used:
                metadata["embedding_fallback_used"] = True
            if draft.section_path:
                metadata["section_path"] = list(draft.section_path)
            if draft.block_kinds:
                metadata["block_kinds"] = list(draft.block_kinds)
            self.session.add(
                KnowledgeChunk(
                    knowledge_version_id=version.id,
                    ordinal=ordinal,
                    content=draft.content,
                    lexical_text=build_lexical_text(draft.content),
                    metadata_json=metadata,
                    embedding=embedding,
                )
            )

    def _resolve_chunking_version(
        self,
        content_blocks: dict[str, Any] | None,
        requested: str | None,
    ) -> str:
        version = requested or self.settings.knowledge_chunking_version
        if version != "v2":
            return "v1"
        blocks = (content_blocks or {}).get("blocks") or []
        return "v2" if blocks else "v1"

    def _chunk_drafts(
        self,
        content: str,
        content_blocks: dict[str, Any] | None,
        *,
        chunking_version: str | None = None,
    ) -> list[ChunkDraft]:
        resolved = chunking_version or self._resolve_chunking_version(
            content_blocks,
            None,
        )
        if resolved == "v2" and content_blocks:
            blocks = content_blocks.get("blocks") or []
            drafts = chunk_blocks(
                blocks,
                target_chars=self.settings.knowledge_chunk_target_chars,
                max_chars=self.settings.knowledge_chunk_max_chars,
            )
            if drafts:
                return drafts
        return [
            ChunkDraft(content=chunk, embedding_text=chunk)
            for chunk in self._chunk_text(content)
        ]

    def _ensure_embedding_usage_scope(
        self,
        *,
        business_unit_id: str,
        correlation_id: str | None,
    ) -> None:
        if not self._uses_default_embedding_provider:
            return
        usage_guard = ModelUsageGuard(
            self.session,
            employee=None,
            business_unit_id=business_unit_id,
            ticket_id=None,
            correlation_id=correlation_id or f"knowledge-{uuid4()}",
        )
        self.embedding_provider = get_embedding_provider(usage_guard)

    def _fail_ingestion(self, version: KnowledgeVersion, error: str) -> None:
        version.status = "FAILED"
        version.ingestion_error = error[:2000]
        version.processed_at = datetime.now(UTC)
        self.session.commit()


def _rrf_fuse(
    rankings: list[list[RetrievalCandidate]],
    *,
    limit: int,
    k: int,
) -> list[RetrievalCandidate]:
    """Merge ranked channels with reciprocal rank fusion.

    Channels are fused by rank rather than score so the dense cosine scale and
    the ts_rank_cd scale never have to be comparable. ``k`` damps the top-rank
    dominance; 60 is the conventional default.
    """
    scores: dict[UUID, float] = {}
    candidates: dict[UUID, RetrievalCandidate] = {}
    for ranking in rankings:
        for position, candidate in enumerate(ranking, start=1):
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1.0 / (
                k + position
            )
            candidates.setdefault(candidate.chunk_id, candidate)
    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [candidates[chunk_id] for chunk_id in ordered[:limit]]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _retrieval_candidate(
    row: tuple[object, ...],
    *,
    vector_score: float,
) -> RetrievalCandidate:
    chunk = cast(KnowledgeChunk, row[0])
    version = cast(KnowledgeVersion, row[1])
    document = cast(KnowledgeDocument, row[2])
    return RetrievalCandidate(
        chunk_id=chunk.id,
        document_id=document.id,
        space_id=document.space_id,
        title=document.title,
        version=version.version_label,
        content=chunk.content,
        vector_score=vector_score,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

