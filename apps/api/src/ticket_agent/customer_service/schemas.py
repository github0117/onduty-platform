from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CustomerConversationCreate(BaseModel):
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    service_entry_id: UUID | None = None
    employee_id: UUID | None = None
    requester_ref: str = Field(default="sandbox-buyer", min_length=1, max_length=128)
    channel: str = Field(default="web_form", min_length=1, max_length=64)
    category_name: str | None = Field(default=None, max_length=120)
    category_profile_id: UUID | None = None


class ConversationTurnView(BaseModel):
    id: UUID
    conversation_id: UUID
    ticket_id: UUID | None
    sequence: int
    status: str
    stage_label: str
    employee_id: UUID | None
    employee_config_revision: int | None
    intent: str | None
    analysis: dict[str, Any]
    response_provider: str | None
    response_model: str | None
    grounding_status: str | None
    citations: list[dict[str, Any]]
    trace: list[str]
    tool_calls: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class CustomerMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    product_id: str | None = Field(default=None, max_length=64)
    sku: str | None = Field(default=None, max_length=100)


class BusinessAddressView(BaseModel):
    recipient: str
    phone: str
    province: str
    city: str
    district: str
    detail: str


class BusinessCustomerView(BaseModel):
    customer_ref: str
    display_name: str
    tier: str
    joined_at: str | None = None


class BusinessOrderView(BaseModel):
    order_id: str
    customer_ref: str
    status: str
    status_label: str
    item_name: str
    amount: float
    currency: str
    order_version: int
    shipping_address: BusinessAddressView
    logistics_status: str | None = None
    logistics_status_label: str | None = None
    after_sales_cases: list[dict[str, Any]] = Field(default_factory=list)


class BusinessResolutionView(BaseModel):
    confidence: float
    matched_by: str
    warnings: list[str] = Field(default_factory=list)


class CustomerBusinessContextView(BaseModel):
    customer_ref: str
    customer: BusinessCustomerView
    order: BusinessOrderView
    resolution: BusinessResolutionView
    source: str


class AddressChangeCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    expected_order_version: int = Field(ge=1)
    recipient: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=32)
    province: str = Field(min_length=1, max_length=80)
    city: str = Field(min_length=1, max_length=80)
    district: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=300)
    reason: str = Field(default="客户申请修改收货地址", max_length=500)
    simulation_mode: Literal["normal", "timeout_unknown", "reject"] = "normal"


class CustomerBusinessActionView(BaseModel):
    conversation_id: UUID
    order_id: str
    action_type: str
    status: str
    message: str
    tool_id: str | None
    tool_call_id: UUID | None
    approval_id: UUID | None
    approval_required_role: str | None
    idempotency_key: str


class CustomerTakeoverRequest(BaseModel):
    expected_version: int = Field(ge=1)


class CustomerManualReplyCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    resolve: bool = False


class CustomerReplySuggestionView(BaseModel):
    text: str
    provider: str
    model: str
    fallback_used: bool
    grounding_status: str
    citations: list[dict[str, Any]]
    skill: str
    trace: list[str]
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class CustomerReplyOptimizationCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    style: Literal["professional", "concise", "empathetic"] = "professional"


class CustomerReplyOptimizationView(BaseModel):
    text: str
    provider: str
    model: str


class AgentHeartbeat(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    status: Literal["ONLINE", "AWAY"] = "ONLINE"
    current_conversation_id: UUID | None = None
    business_unit_id: str = Field(default="bu_demo", min_length=1, max_length=64)
    skills: list[str] = Field(default_factory=list, max_length=50)
    risk_clearance: Literal["R0", "R1", "R2", "R3"] | None = None
    max_conversations: int | None = Field(default=None, ge=1, le=20)
    auto_assign_enabled: bool = True


class AgentPresenceView(BaseModel):
    agent_id: str
    display_name: str
    status: str
    current_conversation_id: UUID | None
    business_unit_id: str
    actor_role: str
    skills: list[str]
    risk_clearance: str
    max_conversations: int
    auto_assign_enabled: bool
    last_seen_at: datetime
    online: bool


class AgentPresenceList(BaseModel):
    items: list[AgentPresenceView]
    online_count: int


class PresenceReclaimResult(BaseModel):
    reclaimed_count: int


class SlaEscalationResult(BaseModel):
    escalated_count: int


class CustomerServiceMetrics(BaseModel):
    total_conversations: int
    active_conversations: int
    unassigned_conversations: int
    online_agents: int
    sla_overdue: int
    open_supervisor_notifications: int
    average_waiting_seconds: int
    total_messages: int
    risk_counts: dict[str, int]


class CustomerDailyMetric(BaseModel):
    date: str
    conversations_created: int
    messages: int
    buyer_messages: int
    assistant_messages: int
    average_first_response_seconds: int | None


class CustomerServiceHistoryMetrics(BaseModel):
    days: int
    conversations_created: int
    messages: int
    unassigned_rate: float
    average_first_response_seconds: int | None
    daily: list[CustomerDailyMetric]


class CustomerServiceNotificationView(BaseModel):
    id: UUID
    business_unit_id: str
    conversation_id: UUID
    severity: str
    title: str
    message: str
    status: str
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    created_at: datetime


class CustomerServiceNotificationList(BaseModel):
    items: list[CustomerServiceNotificationView]
    total: int


class ConversationReassignRequest(BaseModel):
    expected_version: int = Field(ge=1)
    agent_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="SUPERVISOR_REASSIGN", max_length=128)


class CustomerMessageView(BaseModel):
    id: UUID
    sequence: int
    role: Literal["BUYER", "ASSISTANT"]
    content: str
    ticket_id: UUID | None
    created_by: str
    created_at: datetime


class CustomerConversationView(BaseModel):
    id: UUID
    business_unit_id: str
    service_entry_id: UUID | None
    employee_id: UUID | None
    requester_ref: str
    category_name: str | None
    category_profile_id: UUID | None
    channel: str
    status: str
    current_ticket_id: UUID | None
    current_workflow_state: str | None
    current_ticket_status: str | None
    current_risk_level: str | None
    current_priority: str | None
    current_needs_human: bool | None
    assigned_agent_id: str | None
    assigned_at: datetime | None
    version: int
    messages: list[CustomerMessageView]
    current_turn: ConversationTurnView | None = None
    created_at: datetime
    updated_at: datetime


class CustomerConversationList(BaseModel):
    items: list[CustomerConversationView]
    total: int


class AssignmentQueueItem(BaseModel):
    conversation_id: UUID
    requester_ref: str
    current_ticket_id: UUID | None
    priority: str
    risk_level: str | None
    waiting_seconds: int
    created_at: datetime


class AssignmentQueue(BaseModel):
    items: list[AssignmentQueueItem]
    total: int


class AssignmentResultItem(BaseModel):
    conversation_id: UUID
    agent_id: str
    priority: str
    reason: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class AssignmentRunResult(BaseModel):
    assignments: list[AssignmentResultItem]
    assigned_count: int
    unassigned_count: int


class CustomerServiceAlertItem(BaseModel):
    conversation_id: UUID
    requester_ref: str
    assigned_agent_id: str | None
    priority: str
    waiting_seconds: int
    sla_seconds: int
    overdue_seconds: int


class CustomerServiceAlertList(BaseModel):
    items: list[CustomerServiceAlertItem]
    total: int
