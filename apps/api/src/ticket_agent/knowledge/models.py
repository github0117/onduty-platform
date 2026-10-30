from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.knowledge.vector import EmbeddingVector
from ticket_agent.shared.db import Base
from ticket_agent.shared.settings import get_settings

settings = get_settings()


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeSpace(Base):
    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_knowledge_space_business_code",
        ),
        Index("ix_knowledge_spaces_unit_status", "business_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    domain: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    channel: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(128))
    category_profile_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    workflow_key: Mapped[str | None] = mapped_column(String(100))
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evaluation_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_unit", "business_unit_id", "status"),
        Index("ix_knowledge_documents_space", "space_id", "status"),
        UniqueConstraint(
            "business_unit_id",
            "source_type",
            "source_ref",
            name="uq_knowledge_document_source",
        ),
        Index(
            "ix_knowledge_documents_sync",
            "business_unit_id",
            "source_type",
            "sync_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    space_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(64))
    source_ref: Mapped[str | None] = mapped_column(String(200))
    source_version: Mapped[str | None] = mapped_column(String(64))
    sync_status: Mapped[str | None] = mapped_column(String(24))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_label", name="uq_knowledge_version_label"),
        Index("ix_knowledge_versions_active", "status", "effective_from", "effective_to"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_label: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="DRAFT", nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_model: Mapped[str] = mapped_column(String(160), nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_mime_type: Mapped[str | None] = mapped_column(String(128))
    source_size_bytes: Mapped[int | None] = mapped_column(Integer)
    source_object_key: Mapped[str | None] = mapped_column(String(500))
    parser_name: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    content_blocks_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ingestion_error: Mapped[str | None] = mapped_column(Text)
    embedding_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_version", "knowledge_version_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    knowledge_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lexical_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        EmbeddingVector(settings.embedding_dimensions),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DigitalEmployeeKnowledgeBinding(Base):
    __tablename__ = "digital_employee_knowledge_bindings"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "knowledge_space_id",
            "workflow_key",
            name="uq_employee_knowledge_binding",
        ),
        Index(
            "ix_employee_knowledge_bindings_employee",
            "employee_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_space_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_key: Mapped[str | None] = mapped_column(String(100))
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class KnowledgeEvaluationCase(Base):
    __tablename__ = "knowledge_evaluation_cases"
    __table_args__ = (
        Index(
            "ix_knowledge_evaluation_cases_unit_enabled",
            "business_unit_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_space_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    dataset: Mapped[str] = mapped_column(
        String(16),
        default="TUNING",
        server_default="TUNING",
        nullable=False,
    )
    expected_titles_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    expected_chunk_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default=text("'[]'"),
    )
    # Document id plus original text fragment. Resolved to chunk ids at run
    # time so a reindex does not invalidate the case; when present these take
    # precedence over expected_chunk_ids_json.
    expected_passages_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default=text("'[]'"),
    )
    expected_document_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default=text("'[]'"),
    )
    negative_document_ids_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
        server_default=text("'[]'"),
    )
    expect_no_grounding: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    scope_json: Mapped[dict[str, str]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class KnowledgeEvaluationRun(Base):
    __tablename__ = "knowledge_evaluation_runs"
    __table_args__ = (
        Index(
            "ix_knowledge_evaluation_runs_unit_time",
            "business_unit_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset: Mapped[str] = mapped_column(
        String(16),
        default="TUNING",
        server_default="TUNING",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_cases: Mapped[int] = mapped_column(Integer, nullable=False)
    recall_at_k: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    no_grounding_accuracy: Mapped[float | None] = mapped_column(Float)
    chunk_recall_at_k: Mapped[float | None] = mapped_column(Float)
    chunk_mrr: Mapped[float | None] = mapped_column(Float)
    document_recall_at_k: Mapped[float | None] = mapped_column(Float)
    document_mrr: Mapped[float | None] = mapped_column(Float)
    context_precision: Mapped[float | None] = mapped_column(Float)
    negative_violation_rate: Mapped[float | None] = mapped_column(Float)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    baseline_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        default=dict,
        nullable=True,
    )
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeRepairTask(Base):
    __tablename__ = "knowledge_repair_tasks"
    __table_args__ = (
        Index(
            "ix_knowledge_repair_tasks_unit_status",
            "business_unit_id",
            "status",
        ),
        Index(
            "ix_knowledge_repair_tasks_run",
            "evaluation_run_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_space_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
    )
    evaluation_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_evaluation_runs.id", ondelete="SET NULL"),
    )
    evaluation_case_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_evaluation_cases.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(String(24), default="OPEN", nullable=False)
    priority: Mapped[str] = mapped_column(String(8), default="P2", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_titles_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    returned_titles_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    assignee_id: Mapped[str | None] = mapped_column(String(128))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeGapOccurrence(Base):
    """One buyer question the published knowledge could not answer.

    Repair tasks only open after the same question recurs (``NO_KNOWLEDGE``
    threshold), so the raw occurrences need to be durable: they are the
    evidence that the gap is real and not a one-off phrasing miss.
    """

    __tablename__ = "knowledge_gap_occurrences"
    __table_args__ = (
        Index(
            "ix_knowledge_gap_occurrences_unit_query",
            "business_unit_id",
            "normalized_query",
            "created_at",
        ),
        Index("ix_knowledge_gap_occurrences_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    turn_id: Mapped[UUID | None] = mapped_column(Uuid)
    repair_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_repair_tasks.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class KnowledgeFeedback(Base):
    __tablename__ = "knowledge_feedback"
    __table_args__ = (
        Index(
            "ix_knowledge_feedback_unit_rating",
            "business_unit_id",
            "rating",
        ),
        Index("ix_knowledge_feedback_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    knowledge_space_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[str | None] = mapped_column(Text)
    repair_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_repair_tasks.id", ondelete="SET NULL"),
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


REINDEX_STATUSES = (
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "DEAD_LETTER",
)


class KnowledgeReindexJob(Base):
    __tablename__ = "knowledge_reindex_jobs"
    __table_args__ = (
        Index(
            "ix_knowledge_reindex_jobs_unit_status",
            "business_unit_id",
            "status",
        ),
        Index("ix_knowledge_reindex_jobs_document", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
    )
    target_embedding_model: Mapped[str] = mapped_column(String(160), nullable=False)
    target_chunking_version: Mapped[str] = mapped_column(
        String(16),
        default="v1",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    total_versions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_versions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_versions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_versions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

