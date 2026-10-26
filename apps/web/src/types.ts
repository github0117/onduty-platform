export interface TicketListItem {
  id: string;
  subject: string;
  status: string;
  workflow_state: string;
  category_primary: string | null;
  priority: string | null;
  risk_level: string | null;
  queue_id: string | null;
  needs_human: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface TicketList {
  items: TicketListItem[];
  total: number;
}

export interface Draft {
  id: string;
  text: string;
  status: string;
  generator_provider: string | null;
  generator_model: string | null;
  grounding_status: string;
  citations: Array<{
    document_id: string;
    space_id?: string | null;
    title: string;
    version: string;
  }>;
  claims: Array<{
    text: string;
    claim_type: string;
    cited_chunk_ids: string[];
    verification_verdict?: string;
    verification_confidence?: number | null;
    verification_reason?: string | null;
    verification_provider?: string | null;
  }>;
  created_at: string;
  reviewed_at: string | null;
}

export interface TicketDetail {
  id: string;
  subject: string;
  status: string;
  workflow_state: string;
  category_primary: string | null;
  priority: {
    level: string;
    reason_codes: string[];
  } | null;
  risk_level: string | null;
  queue_id: string | null;
  needs_human: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  business_unit_id: string;
  employee: {
    id: string;
    employee_key: string;
    name: string;
    version: string;
    workflow_key: string;
  };
  source: {
    system: string;
    channel: string;
    external_ticket_id: string;
  };
  requester: {
    external_ref: string;
    customer_tier: string;
  };
  body: string;
  summary: string | null;
  classification: {
    primary: string;
    secondary: string;
    confidence: number;
  } | null;
  risk: {
    level: string;
    tags: string[];
    reason_codes: string[];
  } | null;
  routing: {
    queue_id: string | null;
    needs_human: boolean;
    human_reason: string | null;
  };
  draft: Draft | null;
  sync: {
    status: string;
    attempts: number;
    error: string | null;
    external_request_id: string | null;
    synced_at: string | null;
  };
  allowed_actions: string[];
}

export interface CustomerMessage {
  id: string;
  sequence: number;
  role: "BUYER" | "ASSISTANT";
  content: string;
  ticket_id: string | null;
  created_by: string;
  created_at: string;
}

export interface CustomerConversation {
  id: string;
  business_unit_id: string;
  service_entry_id: string | null;
  employee_id: string | null;
  requester_ref: string;
  category_name: string | null;
  category_profile_id: string | null;
  channel: string;
  status: string;
  current_ticket_id: string | null;
  current_workflow_state: string | null;
  current_ticket_status: string | null;
  current_risk_level: string | null;
  current_priority: string | null;
  current_needs_human: boolean | null;
  assigned_agent_id: string | null;
  assigned_at: string | null;
  version: number;
  messages: CustomerMessage[];
  current_turn: ConversationTurn | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationTurn {
  id: string;
  conversation_id: string;
  ticket_id: string | null;
  sequence: number;
  status: string;
  stage_label: string;
  employee_id: string | null;
  employee_config_revision: number | null;
  intent: string | null;
  analysis: Record<string, unknown>;
  response_provider: string | null;
  response_model: string | null;
  grounding_status: string | null;
  citations: Array<Record<string, unknown>>;
  trace: string[];
  tool_calls: Array<Record<string, unknown>>;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface BusinessServiceEntry {
  id: string;
  business_unit_id: string;
  code: string;
  name: string;
  description: string;
  domain: string;
  channel: string;
  status: string;
  default_employee_id: string | null;
  fallback_employee_id: string | null;
  human_queue_id: string;
  knowledge_scope: Record<string, unknown>;
  sla_policy: Record<string, unknown>;
  employees: Array<{
    employee_id: string;
    employee_key: string;
    employee_name: string;
    role_type: string;
    priority: number;
    enabled: boolean;
    employee_status: string;
  }>;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CustomerConversationList {
  items: CustomerConversation[];
  total: number;
}

export interface CustomerBusinessAddress {
  recipient: string;
  phone: string;
  province: string;
  city: string;
  district: string;
  detail: string;
}

export interface CustomerBusinessContext {
  customer_ref: string;
  customer: {
    customer_ref: string;
    display_name: string;
    tier: string;
    joined_at: string | null;
  };
  order: {
    order_id: string;
    customer_ref: string;
    status: string;
    status_label: string;
    item_name: string;
    amount: number;
    currency: string;
    order_version: number;
    shipping_address: CustomerBusinessAddress;
    logistics_status: string | null;
    logistics_status_label: string | null;
    after_sales_cases: Array<Record<string, unknown>>;
  };
  resolution: {
    confidence: number;
    matched_by: string;
    warnings: string[];
  };
  source: string;
}

export interface CustomerBusinessAction {
  conversation_id: string;
  order_id: string;
  action_type: string;
  status: string;
  message: string;
  tool_id: string | null;
  tool_call_id: string | null;
  approval_id: string | null;
  approval_required_role: string | null;
  idempotency_key: string;
}

export interface CustomerReplySuggestion {
  text: string;
  provider: string;
  model: string;
  fallback_used: boolean;
  grounding_status: string;
  citations: Array<{
    chunk_id: string;
    document_id: string;
    space_id: string | null;
    title: string;
    version: string;
  }>;
  skill: string;
  trace: string[];
  tool_calls: Array<{
    tool_call_id: string;
    tool_id: string;
    status: string;
    is_write: boolean;
    duration_ms: number;
    error_code: string | null;
    approval_id: string | null;
    approval_required_role: string | null;
  }>;
}

export interface CustomerReplyOptimization {
  text: string;
  provider: string;
  model: string;
}

export interface AgentPresence {
  agent_id: string;
  display_name: string;
  status: string;
  current_conversation_id: string | null;
  business_unit_id: string;
  actor_role: string;
  skills: string[];
  risk_clearance: string;
  max_conversations: number;
  auto_assign_enabled: boolean;
  last_seen_at: string;
  online: boolean;
}

export interface AgentPresenceList {
  items: AgentPresence[];
  online_count: number;
}

export interface AssignmentQueueItem {
  conversation_id: string;
  requester_ref: string;
  current_ticket_id: string | null;
  priority: string;
  risk_level: string | null;
  waiting_seconds: number;
  created_at: string;
}

export interface AssignmentQueue {
  items: AssignmentQueueItem[];
  total: number;
}

export interface AssignmentRunResult {
  assignments: Array<{
    conversation_id: string;
    agent_id: string;
    priority: string;
    reason: string;
    candidates: Array<{
      agent_id: string;
      eligible: boolean;
      excluded_reasons: string[];
      load: number;
      max_conversations: number;
      risk_clearance: string;
      skills: string[];
      load_ratio: number;
      selected: boolean;
    }>;
  }>;
  assigned_count: number;
  unassigned_count: number;
}

export interface CustomerServiceAlert {
  conversation_id: string;
  requester_ref: string;
  assigned_agent_id: string | null;
  priority: string;
  waiting_seconds: number;
  sla_seconds: number;
  overdue_seconds: number;
}

export interface CustomerServiceAlertList {
  items: CustomerServiceAlert[];
  total: number;
}

export interface CustomerServiceNotification {
  id: string;
  business_unit_id: string;
  conversation_id: string;
  severity: string;
  title: string;
  message: string;
  status: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
}

export interface CustomerServiceNotificationList {
  items: CustomerServiceNotification[];
  total: number;
}

export interface CustomerServiceMetrics {
  total_conversations: number;
  active_conversations: number;
  unassigned_conversations: number;
  online_agents: number;
  sla_overdue: number;
  open_supervisor_notifications: number;
  average_waiting_seconds: number;
  total_messages: number;
  risk_counts: Record<string, number>;
}

export interface CustomerDailyMetric {
  date: string;
  conversations_created: number;
  messages: number;
  buyer_messages: number;
  assistant_messages: number;
  average_first_response_seconds: number | null;
}

export interface CustomerServiceHistoryMetrics {
  days: number;
  conversations_created: number;
  messages: number;
  unassigned_rate: number;
  average_first_response_seconds: number | null;
  daily: CustomerDailyMetric[];
}

export interface LogisticsEvent {
  occurred_at: string | null;
  location: string | null;
  description: string;
}

export interface LogisticsStatus {
  order_id: string | null;
  tracking_number: string | null;
  carrier_code: string | null;
  status: string;
  status_label: string;
  latest_event_at: string | null;
  events: LogisticsEvent[];
}

export interface DigitalEmployee {
  id: string;
  employee_key: string;
  name: string;
  version: string;
  scenario_type: string;
  domain: string;
  template_code: string | null;
  workflow_key: string;
  business_unit_id: string;
  service_identity: string;
  status: string;
  handoff_queue: string;
  knowledge_policy: Record<string, unknown>;
  model_profile: Record<string, unknown>;
  tool_allowlist: string[];
  instruction: string;
  manifest: Record<string, unknown>;
  activation_evaluation: {
    passed?: boolean;
    checks?: Array<{
      key: string;
      label: string;
      status: string;
      detail: string;
    }>;
  };
  activation_evaluated_at: string | null;
  config_revision: number;
  created_at: string;
  updated_at: string;
}

export interface DigitalEmployeeTemplate {
  id: string | null;
  code: string;
  name: string;
  description: string;
  domain: string;
  workflow_key: string;
  scenario_type: string;
  handoff_queue: string;
  capabilities: string[];
  intents: string[];
  skill_codes: string[];
  tool_allowlist: string[];
  status: string;
  builtin: boolean;
  source_draft_id: string | null;
  version: number;
  published_at: string | null;
  knowledge_bindings: Array<Record<string, unknown>>;
  mcp_bindings: Array<Record<string, unknown>>;
  model_profile: Record<string, unknown>;
  knowledge_policy: Record<string, unknown>;
  readiness_snapshot: Record<string, unknown>;
}

export interface DigitalEmployeeRevision {
  id: string;
  employee_id: string;
  revision: number;
  status: string;
  manifest: Record<string, unknown>;
  change_note: string;
  created_by: string;
  created_at: string;
  published_at: string | null;
}

export interface DigitalEmployeeRouteRule {
  id: string;
  business_unit_id: string;
  employee_id: string;
  intents: string[];
  categories: string[];
  channels: string[];
  priority: number;
  fallback: boolean;
  enabled: boolean;
  updated_at: string;
}

export interface DigitalEmployeeRouteDecision {
  id: string;
  business_unit_id: string;
  ticket_id: string | null;
  conversation_id: string | null;
  selected_employee_id: string;
  selected_employee_key: string;
  candidates: DigitalEmployeeRouteCandidate[];
  reason_code: string;
  reason: string;
  score: number;
  confidence: number;
  created_at: string;
}

export interface DigitalEmployeeRouteCandidate {
  employee_id: string;
  employee_key: string;
  employee_name: string;
  template_code: string | null;
  status?: string;
  eligible?: boolean;
  excluded_reasons?: string[];
  score: number;
  keyword_score?: number;
  semantic_score?: number;
  matched_intents?: string[];
  matched_direct_terms?: string[];
  matched_subject_terms?: string[];
  matched_body_terms?: string[];
  matched_synonyms?: string[];
  fallback?: boolean;
  priority?: number | null;
  selected?: boolean;
}

export interface DigitalEmployeeRouteDecisionList {
  items: DigitalEmployeeRouteDecision[];
  total: number;
}

export interface WorkforceTaskStep {
  id: string;
  sequence: number;
  title: string;
  instructions: string;
  assigned_employee_id: string;
  assigned_employee_key: string;
  assigned_employee_name: string;
  route_decision_id: string | null;
  required_capability: string | null;
  route_reason_code: string | null;
  route_reason: string | null;
  route_confidence: number | null;
  route_candidates: DigitalEmployeeRouteCandidate[];
  status: string;
  output: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface WorkforceCapabilityGap {
  step_id: string | null;
  sequence: number | null;
  step_title: string;
  required_capability: string;
  assigned_employee_name: string;
  reason: string;
  recommended_template_code: string | null;
  recommended_template_name: string;
  recommended_domain: string;
  recommended_workflow_key: string;
  recommended_capabilities: string[];
  recommended_intents: string[];
  recommended_skills: string[];
  recommended_tools: string[];
  status: "DRAFT_ONLY";
  approval_required: boolean;
}

export interface WorkforceReadinessCheck {
  key: string;
  label: string;
  status: "READY" | "WARNING" | "BLOCKED" | "NOT_APPLICABLE";
  detail: string;
}

export interface WorkforceEmployeeReadiness {
  employee_id: string;
  employee_key: string;
  employee_name: string;
  template_code: string | null;
  step_sequences: number[];
  status: "READY" | "DEGRADED" | "BLOCKED";
  checks: WorkforceReadinessCheck[];
}

export interface WorkforceTask {
  id: string;
  business_unit_id: string;
  title: string;
  objective: string;
  context: Record<string, unknown>;
  supervisor_employee_id: string | null;
  supervisor_employee_name: string | null;
  status: string;
  result_summary: string | null;
  created_by: string;
  steps: WorkforceTaskStep[];
  capability_gaps: WorkforceCapabilityGap[];
  employee_readiness: WorkforceEmployeeReadiness[];
  capability_assessed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkforceTaskList {
  items: WorkforceTask[];
  total: number;
}

export interface DigitalEmployeeDraft {
  id: string;
  business_unit_id: string;
  source_task_id: string | null;
  source_step_id: string | null;
  required_capability: string;
  name: string;
  template_code: string | null;
  domain: string;
  workflow_key: string;
  scenario_type: string;
  handoff_queue: string;
  capabilities: string[];
  intents: string[];
  skill_codes: string[];
  tool_allowlist: string[];
  status: string;
  revision: number;
  review_note: string | null;
  created_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  employee_id: string | null;
  evaluation: {
    passed?: boolean;
    checks?: Array<{
      key: string;
      label: string;
      status: string;
      detail: string;
    }>;
  };
  evaluated_at: string | null;
  published_at: string | null;
  rolled_back_at: string | null;
  promoted_template_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DigitalEmployeeDraftList {
  items: DigitalEmployeeDraft[];
  total: number;
}

export interface DigitalEmployeeDraftRevision {
  id: string;
  draft_id: string;
  revision: number;
  status: string;
  snapshot: Record<string, unknown>;
  change_note: string;
  created_by: string;
  created_at: string;
}

export interface ManagedEmployeeTemplateRevision {
  id: string;
  template_id: string;
  revision: number;
  status: string;
  snapshot: Record<string, unknown>;
  change_note: string;
  created_by: string;
  published_at: string | null;
  created_at: string;
}

export interface KnowledgeSpace {
  id: string;
  business_unit_id: string;
  code: string;
  name: string;
  description: string;
  domain: string;
  channel: string | null;
  category: string | null;
  category_profile_id: string | null;
  workflow_key: string | null;
  owner_id: string;
  evaluation_required: boolean;
  status: string;
  document_count: number;
  created_at: string;
  updated_at: string;
}

export interface EmployeeKnowledgeBinding {
  id: string;
  employee_id: string;
  knowledge_space_id: string;
  workflow_key: string | null;
  scope: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentSkill {
  id: string;
  business_unit_id: string;
  code: string;
  name: string;
  description: string;
  instructions: string;
  triggers: string[];
  tools: string[];
  status: string;
  version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EmployeeSkillBinding {
  id: string;
  employee_id: string;
  skill_id: string;
  skill_code: string;
  skill_name: string;
  enabled: boolean;
  priority: number;
}

export interface McpTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  is_write: boolean;
}

export interface McpConnector {
  id: string;
  business_unit_id: string;
  code: string;
  name: string;
  description: string;
  transport: string;
  url: string;
  header_env: Record<string, string>;
  timeout_seconds: number;
  status: string;
  tools: McpTool[];
  last_checked_at: string | null;
  last_check_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpHealth {
  connector_id: string;
  healthy: boolean;
  tool_count: number;
  tools: McpTool[];
  error: string | null;
  checked_at: string;
}

export interface EmployeeMcpBinding {
  id: string;
  employee_id: string;
  connector_id: string;
  connector_code: string;
  connector_name: string;
  enabled: boolean;
  allowed_tools: string[];
  write_approved: boolean;
}

export interface McpToolApproval {
  id: string;
  business_unit_id: string;
  employee_id: string;
  connector_id: string;
  ticket_id: string | null;
  conversation_id: string | null;
  tool_id: string;
  connector_code: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  required_role: string;
  policy: Record<string, unknown>;
  status: string;
  requested_by: string;
  request_correlation_id: string;
  reason: string;
  decided_by: string | null;
  decision_note: string | null;
  result: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  version: number;
  decided_at: string | null;
  execution_started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpToolApprovalList {
  items: McpToolApproval[];
  total: number;
}

export interface McpActionIncident {
  id: string;
  business_unit_id: string;
  approval_id: string;
  employee_id: string;
  ticket_id: string | null;
  conversation_id: string | null;
  tool_id: string;
  failure_class: string;
  status: string;
  error_code: string | null;
  error_message: string | null;
  required_action: string;
  assigned_to: string | null;
  resolution_note: string | null;
  resolution_outcome: string | null;
  reconciliation_status: string;
  reconciliation_tool_id: string | null;
  reconciliation_arguments: Record<string, unknown>;
  reconciliation_result: Record<string, unknown>;
  reconciliation_tool_call_id: string | null;
  reconciliation_attempts: number;
  last_reconciled_at: string | null;
  compensation_tool_id: string | null;
  compensation_approval_id: string | null;
  compensation_status: string;
  compensation_result: Record<string, unknown>;
  version: number;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpActionIncidentList {
  items: McpActionIncident[];
  total: number;
}

export interface KnowledgeDocument {
  id: string;
  space_id: string | null;
  business_unit_id: string;
  title: string;
  doc_type: string;
  owner_id: string;
  scope: Record<string, unknown>;
  source_type: string | null;
  source_ref: string | null;
  source_version: string | null;
  sync_status: string | null;
  last_synced_at: string | null;
  status: string;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeVersion {
  id: string;
  document_id: string;
  version_label: string;
  status: string;
  content_hash: string;
  effective_from: string;
  effective_to: string | null;
  embedding_model: string;
  source_filename: string | null;
  source_mime_type: string | null;
  source_size_bytes: number | null;
  source_object_key: string | null;
  parser_name: string | null;
  parser_version: string | null;
  ingestion_error: string | null;
  processing_started_at: string | null;
  processed_at: string | null;
  chunk_count: number;
  published_at: string | null;
  created_at: string;
}

export interface KnowledgeHit {
  chunk_id: string;
  document_id: string;
  space_id: string | null;
  title: string;
  version: string;
  content: string;
  score: number;
}

export interface ProductKnowledgeSyncItem {
  product_id: string;
  sku: string;
  document_id: string | null;
  version_id: string | null;
  status: string;
  changed: boolean;
  error_message: string | null;
}

export interface ProductKnowledgeSyncResult {
  business_unit_id: string;
  requested: number;
  synced: number;
  unchanged: number;
  failed: number;
  items: ProductKnowledgeSyncItem[];
}

export interface KnowledgeEvaluationCase {
  id: string;
  business_unit_id: string;
  knowledge_space_id: string | null;
  employee_id: string | null;
  name: string;
  query: string;
  expected_titles: string[];
  expect_no_grounding: boolean;
  scope: Record<string, string>;
  enabled: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeEvaluationRun {
  id: string;
  business_unit_id: string;
  status: string;
  verdict: string;
  top_k: number;
  case_count: number;
  passed_cases: number;
  failed_cases: number;
  recall_at_k: number | null;
  mrr: number | null;
  no_grounding_accuracy: number | null;
  thresholds: Record<string, number>;
  results: Array<{
    query: string;
    recall_at_k: number;
    reciprocal_rank: number;
    returned_titles: string[];
    no_grounding_correct: boolean | null;
  }>;
  error_message: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface KnowledgeEvaluationRunList {
  items: KnowledgeEvaluationRun[];
  total: number;
}

export interface KnowledgeRepairTask {
  id: string;
  business_unit_id: string;
  knowledge_space_id: string | null;
  evaluation_run_id: string | null;
  evaluation_case_id: string | null;
  status: string;
  priority: string;
  title: string;
  query: string;
  expected_titles: string[];
  returned_titles: string[];
  assignee_id: string | null;
  resolution_note: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  occurrence_count: number;
}

export interface KnowledgeRepairTaskList {
  items: KnowledgeRepairTask[];
  total: number;
}

export interface KnowledgeFeedback {
  id: string;
  business_unit_id: string;
  knowledge_space_id: string | null;
  employee_id: string | null;
  ticket_id: string | null;
  query: string;
  answer: string;
  rating: string;
  reason_code: string;
  details: string | null;
  repair_task_id: string | null;
  created_by: string;
  created_at: string;
}

export interface KnowledgeFeedbackList {
  items: KnowledgeFeedback[];
  total: number;
}

export interface KnowledgeFeedbackCluster {
  knowledge_space_id: string | null;
  reason_code: string;
  count: number;
  repair_task_ids: string[];
  latest_query: string;
}

export interface KnowledgeFeedbackClusterList {
  items: KnowledgeFeedbackCluster[];
  total: number;
}

export interface ToolCall {
  id: string;
  employee_id: string;
  ticket_id: string | null;
  tool_key: string;
  action_type: string;
  risk_level: string;
  status: string;
  correlation_id: string;
  request_payload: Record<string, unknown>;
  response_summary: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

export interface ToolCallList {
  items: ToolCall[];
  total: number;
}

export interface ToolMetricItem {
  tool_key: string;
  calls: number;
  succeeded: number;
  failed: number;
  denied: number;
  success_rate: number;
  average_duration_ms: number;
  p95_duration_ms: number;
}

export interface ToolMetrics {
  calls: number;
  succeeded: number;
  failed: number;
  denied: number;
  success_rate: number;
  failure_rate: number;
  average_duration_ms: number;
  p95_duration_ms: number;
  by_tool: ToolMetricItem[];
}

export interface SyncMetrics {
  attempted: number;
  pending: number;
  syncing: number;
  retrying: number;
  succeeded: number;
  failed: number;
  terminal_count: number;
  success_rate: number;
  failure_rate: number;
  average_attempts: number;
  alerts: string[];
}

export interface ModelMetrics {
  calls: number;
  succeeded: number;
  failed: number;
  denied: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  budget_exceeded: number;
  budget_forecast_alerts: number;
  by_purpose: Array<{
    purpose: string;
    calls: number;
    total_tokens: number;
    estimated_cost: number;
  }>;
}

export interface ModelBudgetPeriod {
  period: string;
  starts_at: string;
  ends_at: string;
  elapsed_fraction: number;
  usage: Record<string, number>;
  limits: Record<string, number>;
  utilization: Record<string, number>;
  projected: Record<string, number>;
  alerts: string[];
}

export interface ModelBudget {
  employee_id: string;
  business_unit_id: string;
  exceeded: boolean;
  forecast_alert: boolean;
  periods: ModelBudgetPeriod[];
}

export interface RagMetrics {
  draft_count: number;
  grounded_count: number;
  no_knowledge_count: number;
  citation_total: number;
  average_citations: number;
  grounding_rate: number;
  claim_count: number;
  cited_claim_count: number;
  policy_claim_count: number;
  policy_citation_coverage: number;
  semantic_verified_claim_count: number;
  semantic_unsupported_claim_count: number;
  provider_counts: Record<string, number>;
}

export interface RuntimeConfig {
  app_env: string;
  task_mode: string;
  object_storage_provider: string;
  model_provider: string;
  model_name: string;
  model_base_url_configured: boolean;
  model_api_key_configured: boolean;
  model_fallback_to_local: boolean;
  embedding_provider: string;
  embedding_model_name: string;
  embedding_base_url_configured: boolean;
  embedding_api_key_configured: boolean;
  embedding_dimensions: number;
  claim_verifier_provider: string;
  claim_verifier_model_name: string;
  claim_verifier_enforce: boolean;
  rerank_provider: string;
  rerank_model_name: string;
  rerank_fallback_to_local: boolean;
  ticket_integration_provider: string;
  ticket_api_url_configured: boolean;
  ticket_api_key_configured: boolean;
  customer_service_auto_reply_enabled: boolean;
  customer_service_auto_reply_min_confidence: number;
  customer_service_auto_reply_max_characters: number;
  ecommerce_channel_provider: string;
  ecommerce_channel_url_configured: boolean;
  ecommerce_channel_api_key_configured: boolean;
  logistics_query_provider: string;
  logistics_query_url_configured: boolean;
  logistics_query_api_key_configured: boolean;
  ecommerce_image_provider: string;
  ecommerce_image_model_name: string;
  ecommerce_image_base_url_configured: boolean;
  ecommerce_image_api_key_configured: boolean;
  ecommerce_visual_audit_provider: string;
  ecommerce_visual_audit_model_name: string;
  ecommerce_visual_audit_api_key_configured: boolean;
  ecommerce_tts_provider: string;
  ecommerce_tts_model_name: string;
  ecommerce_tts_voice: string;
  ecommerce_tts_api_key_configured: boolean;
  ecommerce_content_provider: string;
  ecommerce_content_model_name: string;
  ecommerce_content_base_url_configured: boolean;
  ecommerce_content_api_key_configured: boolean;
  ecommerce_content_fallback_to_local: boolean;
}

export interface AgentRun {
  id: string;
  business_unit_id: string;
  employee_id: string;
  employee_name: string;
  employee_key: string;
  ticket_id: string | null;
  ticket_subject: string | null;
  run_type: string;
  workflow_key: string;
  status: string;
  correlation_id: string;
  input_summary: Record<string, unknown>;
  result_summary: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

export interface AgentRunList {
  items: AgentRun[];
  total: number;
}

export interface AgentTraceEvent {
  id: string;
  event_type: string;
  title: string;
  status: string;
  timestamp: string;
  duration_ms: number | null;
  detail: Record<string, unknown>;
}

export interface AgentRunTrace {
  run: AgentRun;
  events: AgentTraceEvent[];
}

export interface EcommerceProduct {
  id: string;
  business_unit_id: string;
  sku: string;
  name: string;
  category: string;
  brand: string | null;
  price: number;
  attributes: Record<string, unknown>;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EcommerceCategoryProfile {
  id: string;
  business_unit_id: string;
  channel: string;
  code: string;
  name: string;
  platform_category_id: string | null;
  required_attributes: string[];
  presales_keywords: string[];
  aftersales_keywords: string[];
  restricted_claims: string[];
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EcommerceProductImportRow {
  row_number: number;
  sku: string;
  name: string;
  category: string;
  brand: string;
  valid: boolean;
  errors: string[];
  price: number | null;
  attributes: Record<string, unknown>;
}

export interface EcommerceProductImportPreview {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  columns: string[];
  rows: EcommerceProductImportRow[];
}

export interface EcommerceProductImportResult {
  requested_rows: number;
  created_count: number;
  skipped_count: number;
  products: EcommerceProduct[];
  errors: string[];
}

export interface EcommerceProductAsset {
  id: string;
  product_id: string;
  business_unit_id: string;
  owner_employee_id: string | null;
  asset_type: "IMAGE" | "VIDEO" | "SUBTITLE" | "AUDIO";
  filename: string;
  content_type: string;
  size_bytes: number;
  status: string;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
}

export interface EcommerceImageGeneration {
  id: string;
  business_unit_id: string;
  product_id: string;
  provider: string;
  model_name: string;
  prompt: string;
  requested_count: number;
  succeeded_count: number;
  fallback_used: boolean;
  estimated_cost: number;
  status: string;
  error_message: string | null;
  correlation_id: string;
  created_at: string;
  completed_at: string | null;
}

export interface EcommerceImageGenerationList {
  items: EcommerceImageGeneration[];
  total_images: number;
  estimated_cost: number;
}

export interface EcommerceVideoRenderJob {
  id: string;
  business_unit_id: string;
  product_id: string;
  listing_task_id: string;
  generation_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress: number;
  scene_count: number;
  duration_seconds: number;
  asset_id: string | null;
  background_music_asset_id: string | null;
  background_music_volume: number;
  error_message: string | null;
  correlation_id: string;
  created_by: string;
  retry_count: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

export interface EcommerceVideoRenderJobList {
  items: EcommerceVideoRenderJob[];
  total: number;
}

export interface EcommerceOperationalMetrics {
  business_unit_id: string;
  total_listings: number;
  pending_review: number;
  needs_human: number;
  publishing: number;
  published: number;
  rejected: number;
  failed: number;
  publication_success_rate: number;
  human_intervention_rate: number;
  average_publish_seconds: number | null;
  market_breakdown: Record<string, number>;
  video_jobs: number;
  video_succeeded: number;
  video_failed: number;
  video_active: number;
  video_success_rate: number;
  average_render_seconds: number | null;
  generated_images: number;
  estimated_image_cost: number;
}

export interface EcommerceListingItem {
  id: string;
  product_id: string;
  sku: string;
  product_name: string;
  channel: string;
  market_code: string;
  owner_employee_id: string | null;
  locale: string;
  currency: string;
  sale_price: number;
  status: string;
  risk_level: string;
  version: number;
  human_reason: string | null;
  external_listing_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface EcommerceListingList {
  items: EcommerceListingItem[];
  total: number;
}

export interface EcommerceListingBatchItem {
  id: string;
  product_id: string;
  status: string;
  listing_task_id: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface EcommerceListingBatchJob {
  id: string;
  business_unit_id: string;
  channel: string;
  market_code: string;
  status: string;
  total_count: number;
  succeeded_count: number;
  failed_count: number;
  error_message: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  items: EcommerceListingBatchItem[];
}

export interface EcommerceListingBatchJobList {
  items: EcommerceListingBatchJob[];
  total: number;
}

export interface EcommerceListingDetail extends EcommerceListingItem {
  business_unit_id: string;
  product_category: string;
  content: {
    title?: string;
    selling_points?: string[];
    detail_description?: string;
    short_video_script?: Array<{ second: string; visual: string; line: string }>;
    hashtags?: string[];
  };
  compliance: {
    restricted_claims?: string[];
    rule_count?: number;
    checked?: boolean;
    missing_product_image?: boolean;
    required_attributes_missing?: string[];
    channel_required_attributes_missing?: string[];
    primary_image_visual_audit_status?: string;
    content_provider?: string;
    content_model?: string;
    content_fallback_used?: boolean;
  };
  citations: Array<{
    chunk_id: string;
    document_id: string;
    space_id?: string | null;
    title: string;
    version: string;
  }>;
  generator_provider: string;
  generator_model: string;
  error_message: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  published_at: string | null;
}

