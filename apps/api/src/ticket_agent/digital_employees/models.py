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
)
from sqlalchemy.orm import Mapped, mapped_column

from ticket_agent.shared.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class DigitalEmployee(Base):
    __tablename__ = "digital_employees"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "employee_key",
            name="uq_digital_employee_business_key",
        ),
        Index("ix_digital_employees_unit_status", "business_unit_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(
        String(64),
        default="customer_service",
        nullable=False,
    )
    template_code: Mapped[str | None] = mapped_column(String(100))
    workflow_key: Mapped[str] = mapped_column(String(100), nullable=False)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    handoff_queue: Mapped[str] = mapped_column(
        String(64), default="MANUAL_TRIAGE", nullable=False
    )
    knowledge_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    model_profile_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    tool_allowlist_json: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    # 员工级提示词：operator 配置的角色、语气和服务边界。生成时作为
    # 系统提示词的一个独立区块注入，不能覆盖安全约束和知识事实。
    instruction_text: Mapped[str] = mapped_column(
        Text, default="", nullable=False
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    activation_evaluation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    activation_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    config_revision: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class DigitalEmployeeRevision(Base):
    __tablename__ = "digital_employee_revisions"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "revision",
            name="uq_digital_employee_revision",
        ),
        Index(
            "ix_employee_revisions_employee_time",
            "employee_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="PUBLISHED",
        nullable=False,
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    instruction_text: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    change_note: Mapped[str] = mapped_column(
        String(500),
        default="",
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )


class DigitalEmployeeDraft(Base):
    __tablename__ = "digital_employee_drafts"
    __table_args__ = (
        UniqueConstraint(
            "source_task_id",
            "required_capability",
            name="uq_employee_draft_task_capability",
        ),
        Index(
            "ix_employee_drafts_unit_status",
            "business_unit_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("workforce_tasks.id", ondelete="CASCADE"),
    )
    source_step_id: Mapped[UUID | None] = mapped_column(Uuid)
    required_capability: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    template_code: Mapped[str | None] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_queue: Mapped[str] = mapped_column(
        String(64),
        default="MANUAL_TRIAGE",
        nullable=False,
    )
    capabilities_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    intents_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    skill_codes_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    tool_allowlist_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="DRAFT",
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    employee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="SET NULL"),
    )
    evaluation_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    promoted_template_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "digital_employee_templates.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_employee_draft_promoted_template",
        ),
    )
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


class DigitalEmployeeDraftRevision(Base):
    __tablename__ = "digital_employee_draft_revisions"
    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "revision",
            name="uq_employee_draft_revision",
        ),
        Index(
            "ix_employee_draft_revisions_draft_time",
            "draft_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "digital_employee_drafts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    change_note: Mapped[str] = mapped_column(
        String(500),
        default="",
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class DigitalEmployeeManagedTemplate(Base):
    __tablename__ = "digital_employee_templates"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "code",
            name="uq_digital_employee_template_code",
        ),
        Index(
            "ix_employee_templates_unit_status",
            "business_unit_id",
            "status",
            "created_at",
        ),
        UniqueConstraint(
            "source_draft_id",
            name="uq_employee_template_source_draft",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_queue: Mapped[str] = mapped_column(String(64), nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    intents_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    skill_codes_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    tool_allowlist_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    knowledge_bindings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    mcp_bindings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    model_profile_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    knowledge_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    readiness_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        default="DRAFT",
        nullable=False,
    )
    source_draft_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("digital_employee_drafts.id", ondelete="SET NULL"),
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
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


class DigitalEmployeeTemplateRevision(Base):
    __tablename__ = "digital_employee_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "revision",
            name="uq_employee_template_revision",
        ),
        Index(
            "ix_employee_template_revisions_template_time",
            "template_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "digital_employee_templates.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    change_note: Mapped[str] = mapped_column(
        String(500),
        default="",
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )


class DigitalEmployeeRouteRule(Base):
    __tablename__ = "digital_employee_route_rules"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            name="uq_digital_employee_route_rule",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intents_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    categories_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    channels_json: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    fallback: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
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


class DigitalEmployeeRouteDecision(Base):
    __tablename__ = "digital_employee_route_decisions"
    __table_args__ = (
        Index(
            "ix_employee_route_decisions_unit_time",
            "business_unit_id",
            "created_at",
        ),
        Index(
            "ix_employee_route_decisions_ticket",
            "ticket_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid)
    conversation_id: Mapped[UUID | None] = mapped_column(Uuid)
    selected_employee_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    selected_employee_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )



class DigitalEmployeeRouteEvaluationCase(Base):
    __tablename__ = "digital_employee_route_evaluation_cases"
    __table_args__ = (
        UniqueConstraint(
            "business_unit_id",
            "service_entry_id",
            "question",
            name="uq_route_evaluation_case_question",
        ),
        Index(
            "ix_route_evaluation_cases_entry_enabled",
            "service_entry_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("business_service_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    expected_employee_id: Mapped[UUID] = mapped_column(
        ForeignKey("digital_employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
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


class DigitalEmployeeRouteEvaluationRun(Base):
    __tablename__ = "digital_employee_route_evaluation_runs"
    __table_args__ = (
        Index(
            "ix_route_evaluation_runs_unit_time",
            "business_unit_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    business_unit_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("business_service_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(128),
        default="system",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
