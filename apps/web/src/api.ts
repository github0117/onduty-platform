import type {
  AgentRunList,
  AgentRunTrace,
  AgentSkill,
  AnswerQualityEvaluation,
  AnswerQualitySampleList,
  AnswerQualitySummary,
  AnswerQualityVerdict,
  BusinessServiceEntry,
  AgentPresence,
  AgentPresenceList,
  AssignmentQueue,
  AssignmentRunResult,
  DigitalEmployee,
  DigitalEmployeeDraft,
  DigitalEmployeeDraftList,
  DigitalEmployeeDraftRevision,
  DigitalEmployeeRevision,
  DigitalEmployeeRouteDecisionList,
  DigitalEmployeeRouteEvaluationCase,
  DigitalEmployeeRouteEvaluationDataset,
  DigitalEmployeeRouteEvaluationRun,
  DigitalEmployeeRouteEvaluationRunList,
  DigitalEmployeeRouteIntentConflictList,
  DigitalEmployeeRouteRule,
  DigitalEmployeeTemplate,
  CustomerConversation,
  CustomerConversationList,
  CustomerBusinessAction,
  CustomerBusinessContext,
  CustomerReplyOptimization,
  CustomerReplySuggestion,
  CustomerServiceAlertList,
  CustomerServiceNotification,
  CustomerServiceNotificationList,
  CustomerServiceMetrics,
  CustomerServiceHistoryMetrics,
  CustomerValueMetrics,
  EmployeeKnowledgeBinding,
  EmployeeMcpBinding,
  EmployeeSkillBinding,
  EcommerceListingDetail,
  EcommerceListingBatchJob,
  EcommerceListingBatchJobList,
  EcommerceListingList,
  EcommerceImageGenerationList,
  EcommerceProductAsset,
  EcommerceProduct,
  EcommerceCategoryProfile,
  EcommerceProductImportPreview,
  EcommerceProductImportResult,
  EcommerceOperationalMetrics,
  EcommerceVideoRenderJob,
  EcommerceVideoRenderJobList,
  KnowledgeDocument,
  KnowledgeEvaluationCase,
  KnowledgeEvaluationDataset,
  KnowledgeEvaluationRun,
  KnowledgeEvaluationRunList,
  KnowledgeFeedback,
  KnowledgeFeedbackClusterList,
  KnowledgeFeedbackList,
  KnowledgeRepairTask,
  KnowledgeRepairTaskList,
  KnowledgeHit,
  KnowledgeSpace,
  KnowledgeVersion,
  LogisticsStatus,
  ManagedEmployeeTemplateRevision,
  McpConnector,
  McpHealth,
  McpActionIncident,
  McpActionIncidentList,
  McpToolApproval,
  McpToolApprovalList,
  ModelBudget,
  ModelMetrics,
  ProductKnowledgeSyncResult,
  RagMetrics,
  RuntimeConfig,
  SyncMetrics,
  TicketDetail,
  TicketList,
  ToolCallList,
  ToolMetrics,
  WorkforceMetrics,
  WorkforceTask,
  WorkforceTaskList,
} from "./types";
import {
  getActiveBusinessUnitId,
  getAuthHeaders,
  login,
} from "./auth";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

function withActiveBusinessUnit(path: string): string {
  const activeBusinessUnit = getActiveBusinessUnitId();
  if (activeBusinessUnit === "bu_demo" || !path.includes("bu_demo")) {
    return path;
  }
  const [withoutHash, hash = ""] = path.split("#", 2);
  const [pathname, search] = withoutHash.split("?", 2);
  if (!search) return path;
  const query = new URLSearchParams(search);
  if (query.get("business_unit_id") !== "bu_demo") return path;
  query.set("business_unit_id", activeBusinessUnit);
  return `${pathname}?${query.toString()}${hash ? `#${hash}` : ""}`;
}

function withActiveBusinessUnitBody(init?: RequestInit): RequestInit | undefined {
  if (!init || typeof init.body !== "string") return init;
  const activeBusinessUnit = getActiveBusinessUnitId();
  if (activeBusinessUnit === "bu_demo") return init;
  const contentType = new Headers(init.headers).get("Content-Type");
  if (contentType && !contentType.toLowerCase().startsWith("application/json")) {
    return init;
  }
  let payload: unknown;
  try {
    payload = JSON.parse(init.body);
  } catch {
    return init;
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    (payload as Record<string, unknown>).business_unit_id !== "bu_demo"
  ) {
    return init;
  }
  return {
    ...init,
    body: JSON.stringify({
      ...payload,
      business_unit_id: activeBusinessUnit,
    }),
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | null,
    readonly retryable: boolean,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const friendlyApiErrors: Record<string, string> = {
  KNOWLEDGE_EVALUATION_CASES_EMPTY:
    "至少启用一个评测案例后才能运行评测。",
  KNOWLEDGE_VERSION_EXISTS:
    "该知识版本已存在，请换一个版本号后重试。",
  INVALID_KNOWLEDGE_STATE:
    "知识当前状态不允许执行此操作，请刷新页面后重试。",
  KNOWLEDGE_DOCUMENT_NO_RESTORABLE_VERSION:
    "该文档没有可恢复的有效版本，请重新创建或发布一个知识版本。",
  DEMO_RESET_DISABLED:
    "当前不是演示环境，不能执行演示数据恢复。",
  DEMO_RESET_FAILED:
    "演示数据恢复失败，请检查后台服务后重试。",
  DEMO_RESET_IN_PROGRESS:
    "演示数据正在恢复，请等待当前任务完成后再试。",
  DEMO_RESET_TIMEOUT:
    "演示数据恢复超时，请稍后重试或联系管理员。",
  DEMO_RESET_UNIT_UNSUPPORTED:
    "演示数据恢复只作用于 bu_demo，请先切换到主要演示单元。",
  DEMO_RESET_CONFIRMATION_REQUIRED:
    "需要显式确认后才可恢复演示数据。",
  DEMO_RESET_JOB_NOT_FOUND:
    "恢复任务不存在或服务已重启，请重新提交。",
  SCHEMA_VALIDATION_FAILED:
    "提交内容不符合要求，请检查必填项和格式。",
  RESOURCE_NOT_FOUND:
    "请求的数据不存在，可能已被删除或归档。",
  FORBIDDEN:
    "当前账号没有执行此操作的权限。",
  UNAUTHORIZED:
    "登录状态已失效，请重新登录。",
  WORKFORCE_CAPABILITY_GAP:
    "当前任务仍有能力缺口，暂时不能执行。",
  WORKFORCE_TASK_CONFLICT:
    "任务状态已经变化，请刷新后重新操作。",
  EMPLOYEE_DRAFT_EXISTS:
    "该能力已有员工草案，请到草案页面继续处理。",
  DATABASE_BUSY:
    "演示数据库正在处理其他任务，请等待片刻后重新生成。",
  DATABASE_ERROR:
    "数据库操作失败，请稍后重试。",
};

function friendlyProblem(
  response: Response,
  problem: { detail?: string; code?: string } | null,
): string {
  if (problem?.code && friendlyApiErrors[problem.code]) {
    return friendlyApiErrors[problem.code];
  }
  if (problem?.detail && /[\u4e00-\u9fff]/.test(problem.detail)) {
    return problem.detail;
  }
  if (response.status === 401) return "登录状态已失效，请重新登录。";
  if (response.status === 403) return "当前账号没有执行此操作的权限。";
  if (response.status === 404) {
    return "请求的数据不存在，可能已被删除或归档。";
  }
  if (response.status === 409) {
    return "数据状态已经变化，请刷新页面后重试。";
  }
  if (response.status === 422) {
    return "提交内容不符合要求，请检查必填项和格式。";
  }
  if (response.status >= 500) {
    return "系统处理失败，请稍后重试；如持续失败，请联系管理员。";
  }
  return "操作失败，请检查输入后重试。";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const authHeaders = await getAuthHeaders();
  const resolvedInit = withActiveBusinessUnitBody(init);
  const response = await fetch(`${API_BASE}${withActiveBusinessUnit(path)}`, {
    ...resolvedInit,
    signal: init?.signal ?? AbortSignal.timeout(60_000),
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...resolvedInit?.headers,
    },
  });

  if (!response.ok) {
    if (response.status === 401 && import.meta.env.VITE_AUTH_MODE === "oidc") {
      await login();
    }
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string; code?: string; retryable?: boolean }
      | null;
    throw new ApiError(
      friendlyProblem(response, problem),
      response.status,
      problem?.code ?? null,
      problem?.retryable ?? false,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listTickets(): Promise<TicketList> {
  return request<TicketList>("/api/v1/tickets?business_unit_id=bu_demo&limit=50");
}

export interface DemoResetJob {
  job_id: string;
  business_unit_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  message: string;
  code: string | null;
  created_at?: string;
  updated_at?: string;
  finished_at?: string | null;
}

export function resetDemoData(): Promise<DemoResetJob> {
  return request("/api/v1/demo/reset?business_unit_id=bu_demo", {
    method: "POST",
    headers: { "X-Demo-Reset-Confirm": "reset-bu_demo" },
    body: "{}",
    signal: AbortSignal.timeout(30_000),
  });
}

export function getDemoResetStatus(jobId: string): Promise<DemoResetJob> {
  return request(
    `/api/v1/demo/reset/${encodeURIComponent(jobId)}`,
    { signal: AbortSignal.timeout(15_000) },
  );
}

export function getTicket(id: string): Promise<TicketDetail> {
  return request<TicketDetail>(`/api/v1/tickets/${id}`);
}

export interface CreateDemoTicketInput {
  subject: string;
  body: string;
  employeeId: string;
}

export async function createDemoTicket(input: CreateDemoTicketInput): Promise<TicketDetail> {
  const sourceId = `WEB-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const created = await request<{ id: string }>("/api/v1/tickets", {
    method: "POST",
    headers: { "Idempotency-Key": `demo:${sourceId}` },
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      employee_id: input.employeeId,
      source: {
        system: "demo_helpdesk",
        channel: "web_form",
        external_ticket_id: sourceId,
      },
      requester: {
        external_ref: "customer_demo",
        customer_tier: "standard",
      },
      subject: input.subject,
      body: input.body,
      locale: "zh-CN",
      attachments: [],
      metadata: { product: "admin_portal", origin: "web_demo" },
    }),
  });

  return getTicket(created.id);
}

export async function createEcommerceCustomerTicket(input: {
  subject: string;
  body: string;
  employeeId: string;
  productId?: string;
  sku?: string;
}): Promise<TicketDetail> {
  const sourceId = `ECOM-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const created = await request<{ id: string }>("/api/v1/tickets", {
    method: "POST",
    headers: { "Idempotency-Key": `ecommerce-chat:${sourceId}` },
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      employee_id: input.employeeId,
      source: {
        system: "ecommerce_demo",
        channel: "web_form",
        external_ticket_id: sourceId,
      },
      requester: {
        external_ref: "sandbox-buyer",
        customer_tier: "standard",
      },
      subject: input.subject,
      body: input.body,
      locale: "zh-CN",
      attachments: [],
      metadata: {
        channel: "ecommerce_demo",
        category: "商品",
        ...(input.productId ? { product_id: input.productId } : {}),
        ...(input.sku ? { sku: input.sku } : {}),
      },
    }),
  });
  return getTicket(created.id);
}

export function createCustomerConversation(
  input: {
    employeeId?: string;
    serviceEntryId?: string;
    category?: { name: string; profileId: string };
    scenario?: "enterprise" | "ecommerce";
  } = {},
): Promise<CustomerConversation> {
  const scenario = input.scenario ?? "ecommerce";
  return request("/api/v1/customer-service/conversations", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      ...(input.employeeId ? { employee_id: input.employeeId } : {}),
      ...(input.serviceEntryId
        ? { service_entry_id: input.serviceEntryId }
        : {}),
      requester_ref: `sandbox-buyer-${Date.now()}`,
      channel: scenario === "enterprise" ? "enterprise_service" : "web_form",
      category_name: input.category?.name,
      category_profile_id: input.category?.profileId,
    }),
  });
}

export function listBusinessServiceEntries(): Promise<BusinessServiceEntry[]> {
  return request(
    "/api/v1/business-service-entries?business_unit_id=bu_demo",
  );
}

export function replaceBusinessServiceEntryEmployees(
  entryId: string,
  employees: Array<{
    employeeId: string;
    roleType: "PRIMARY" | "SPECIALIST" | "FALLBACK";
    priority: number;
  }>,
): Promise<BusinessServiceEntry> {
  return request(`/api/v1/business-service-entries/${entryId}/employees`, {
    method: "PUT",
    body: JSON.stringify(
      employees.map((item) => ({
        employee_id: item.employeeId,
        role_type: item.roleType,
        priority: item.priority,
        enabled: true,
      })),
    ),
  });
}

export function getCustomerConversation(
  conversationId: string,
): Promise<CustomerConversation> {
  return request(`/api/v1/customer-service/conversations/${conversationId}`);
}

export function listCustomerConversations(): Promise<CustomerConversationList> {
  return request(
    "/api/v1/customer-service/conversations?business_unit_id=bu_demo",
  );
}

export function getCustomerBusinessContext(
  conversationId: string,
  orderId?: string,
): Promise<CustomerBusinessContext> {
  const suffix = orderId
    ? `?order_id=${encodeURIComponent(orderId)}`
    : "";
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/business-context${suffix}`,
  );
}

export interface AddressChangeInput {
  orderId: string;
  expectedOrderVersion: number;
  recipient: string;
  phone: string;
  province: string;
  city: string;
  district: string;
  detail: string;
  reason: string;
  simulationMode: "normal" | "timeout_unknown" | "reject";
}

export function requestCustomerAddressChange(
  conversationId: string,
  input: AddressChangeInput,
): Promise<CustomerBusinessAction> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/business-actions/address-change`,
    {
      method: "POST",
      body: JSON.stringify({
        order_id: input.orderId,
        expected_order_version: input.expectedOrderVersion,
        recipient: input.recipient,
        phone: input.phone,
        province: input.province,
        city: input.city,
        district: input.district,
        detail: input.detail,
        reason: input.reason,
        simulation_mode: input.simulationMode,
      }),
    },
  );
}

export function heartbeatCustomerAgent(
  currentConversationId?: string,
): Promise<AgentPresence> {
  return request("/api/v1/customer-service/presence/heartbeat", {
    method: "POST",
    body: JSON.stringify({
      display_name: "客服坐席",
      status: "ONLINE",
      current_conversation_id: currentConversationId || null,
    }),
  });
}

export function listCustomerAgentPresence(): Promise<AgentPresenceList> {
  return request("/api/v1/customer-service/presence");
}

export function getCustomerAssignmentQueue(): Promise<AssignmentQueue> {
  return request("/api/v1/customer-service/assignment-queue");
}

export function autoAssignCustomerConversations(): Promise<AssignmentRunResult> {
  return request("/api/v1/customer-service/assignment-queue/auto-assign", {
    method: "POST",
  });
}

export function listCustomerServiceAlerts(): Promise<CustomerServiceAlertList> {
  return request("/api/v1/customer-service/alerts");
}

export function listCustomerServiceNotifications(): Promise<CustomerServiceNotificationList> {
  return request("/api/v1/customer-service/notifications");
}

export function acknowledgeCustomerServiceNotification(
  notificationId: string,
): Promise<CustomerServiceNotification> {
  return request(
    `/api/v1/customer-service/notifications/${notificationId}/acknowledge`,
    { method: "POST" },
  );
}

export function getCustomerServiceMetrics(): Promise<CustomerServiceMetrics> {
  return request("/api/v1/customer-service/metrics?business_unit_id=bu_demo");
}

export function getCustomerValueMetrics(
  days = 30,
): Promise<CustomerValueMetrics> {
  return request(
    `/api/v1/customer-service/value-metrics?business_unit_id=bu_demo&days=${days}`,
  );
}

export function getCustomerServiceHistoryMetrics(
  days = 7,
): Promise<CustomerServiceHistoryMetrics> {
  return request(
    `/api/v1/customer-service/metrics/history?business_unit_id=bu_demo&days=${days}`,
  );
}

export function addCustomerConversationMessage(
  conversationId: string,
  input: { content: string; productId?: string; sku?: string },
): Promise<CustomerConversation> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/messages`,
    {
      method: "POST",
      body: JSON.stringify({
        content: input.content,
        product_id: input.productId,
        sku: input.sku,
      }),
    },
  );
}

export type CustomerTurnStreamEvent =
  | {
      type: "start";
      turn_id: string | null;
      conversation: CustomerConversation;
    }
  | { type: "status"; turn_id: string; stage: string }
  | { type: "delta"; turn_id: string; text: string }
  | { type: "replace"; turn_id: string; text: string }
  | {
      type: "done";
      turn_id: string | null;
      conversation: CustomerConversation;
    }
  | { type: "error"; turn_id: string; message: string };

export async function streamCustomerConversationMessage(
  conversationId: string,
  input: { content: string; productId?: string; sku?: string },
  onEvent: (event: CustomerTurnStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/customer-service/conversations/${conversationId}/messages/stream`,
    {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeaders,
      },
      body: JSON.stringify({
        content: input.content,
        product_id: input.productId,
        sku: input.sku,
      }),
    },
  );
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string; code?: string; retryable?: boolean }
      | null;
    throw new ApiError(
      friendlyProblem(response, problem),
      response.status,
      problem?.code ?? null,
      problem?.retryable ?? false,
    );
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) {
          eventName = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        }
      }
      if (dataLines.length === 0) continue;
      const parsed = JSON.parse(dataLines.join("\n")) as Record<
        string,
        unknown
      >;
      onEvent({
        ...parsed,
        type: (parsed.type as string | undefined) ?? eventName,
      } as CustomerTurnStreamEvent);
    }
  }
}

export function sendManualCustomerReply(
  conversationId: string,
  content: string,
  resolve: boolean,
): Promise<CustomerConversation> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/manual-replies`,
    {
      method: "POST",
      body: JSON.stringify({ content, resolve }),
    },
  );
}

export function queryLogistics(input: {
  orderId?: string;
  trackingNumber?: string;
  carrierCode?: string;
}): Promise<LogisticsStatus> {
  return request("/api/v1/logistics/query", {
    method: "POST",
    body: JSON.stringify({
      order_id: input.orderId || undefined,
      tracking_number: input.trackingNumber || undefined,
      carrier_code: input.carrierCode || undefined,
    }),
  });
}

export function generateCustomerReplySuggestion(
  conversationId: string,
): Promise<CustomerReplySuggestion> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/reply-suggestions`,
    { method: "POST" },
  );
}

export function optimizeCustomerReply(
  conversationId: string,
  text: string,
  style: "professional" | "concise" | "empathetic",
): Promise<CustomerReplyOptimization> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/reply-optimizations`,
    {
      method: "POST",
      body: JSON.stringify({ text, style }),
    },
  );
}

export function takeOverCustomerConversation(
  conversationId: string,
  expectedVersion: number,
): Promise<CustomerConversation> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/takeover`,
    {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion }),
    },
  );
}

export function releaseCustomerConversation(
  conversationId: string,
): Promise<CustomerConversation> {
  return request(
    `/api/v1/customer-service/conversations/${conversationId}/release`,
    { method: "POST" },
  );
}

export async function watchCustomerConversation(
  conversationId: string,
  onConversation: (conversation: CustomerConversation) => void,
  signal: AbortSignal,
): Promise<void> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/customer-service/conversations/${conversationId}/events`,
    {
      headers: { ...authHeaders, Accept: "text/event-stream" },
      signal,
    },
  );
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) {
        onConversation(JSON.parse(data) as CustomerConversation);
      }
    }
  }
}

export function createKnowledgeFeedback(input: {
  employeeId: string;
  knowledgeSpaceId: string;
  ticketId: string;
  query: string;
  answer: string;
  rating: "POSITIVE" | "NEGATIVE";
  reasonCode: string;
  details?: string;
}): Promise<{ id: string; repair_task_id: string | null }> {
  return request("/api/v1/knowledge/feedback", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      knowledge_space_id: input.knowledgeSpaceId,
      employee_id: input.employeeId,
      ticket_id: input.ticketId,
      query: input.query,
      answer: input.answer,
      rating: input.rating,
      reason_code: input.reasonCode,
      details: input.details,
    }),
  });
}

export function listDigitalEmployees(): Promise<DigitalEmployee[]> {
  return request("/api/v1/digital-employees?business_unit_id=bu_demo");
}

export function listDigitalEmployeeTemplates(): Promise<
  DigitalEmployeeTemplate[]
> {
  return request(
    "/api/v1/digital-employee-templates?business_unit_id=bu_demo",
  );
}

export function listManagedEmployeeTemplates(): Promise<
  DigitalEmployeeTemplate[]
> {
  return request(
    "/api/v1/digital-employee-templates/managed?business_unit_id=bu_demo",
  );
}

export function promoteEmployeeDraftToTemplate(
  draftId: string,
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-drafts/${draftId}/promote-template`,
    { method: "POST" },
  );
}

export function reviewManagedEmployeeTemplate(
  templateId: string,
  input: {
    decision: "APPROVE" | "REJECT";
    note?: string;
  },
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/review`,
    {
      method: "POST",
      body: JSON.stringify({
        decision: input.decision,
        note: input.note ?? "",
      }),
    },
  );
}

export function updateManagedEmployeeTemplate(
  templateId: string,
  input: {
    name?: string;
    description?: string;
    capabilities?: string[];
    intents?: string[];
    skillCodes?: string[];
    toolAllowlist?: string[];
    knowledgeBindings?: Array<Record<string, unknown>>;
    mcpBindings?: Array<Record<string, unknown>>;
  },
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/edit`,
    {
      method: "POST",
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        capabilities: input.capabilities,
        intents: input.intents,
        skill_codes: input.skillCodes,
        tool_allowlist: input.toolAllowlist,
        knowledge_bindings: input.knowledgeBindings,
        mcp_bindings: input.mcpBindings,
      }),
    },
  );
}

export function publishManagedEmployeeTemplate(
  templateId: string,
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/publish`,
    { method: "POST" },
  );
}

export function rollbackManagedEmployeeTemplate(
  templateId: string,
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/rollback`,
    { method: "POST" },
  );
}

export function reopenManagedEmployeeTemplate(
  templateId: string,
): Promise<DigitalEmployeeTemplate> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/reopen`,
    { method: "POST" },
  );
}

export function listManagedEmployeeTemplateRevisions(
  templateId: string,
): Promise<ManagedEmployeeTemplateRevision[]> {
  return request(
    `/api/v1/digital-employee-templates/${templateId}/revisions`,
  );
}

export function createDigitalEmployeeFromTemplate(input: {
  name: string;
  templateCode: string;
  knowledgeSpaceIds?: string[];
  skillIds?: string[];
  mcpConnectorIds?: string[];
  instruction?: string;
  changeNote?: string;
}): Promise<DigitalEmployee> {
  return request("/api/v1/digital-employees/from-template", {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      template_code: input.templateCode,
      business_unit_id: "bu_demo",
      knowledge_space_ids: input.knowledgeSpaceIds ?? [],
      skill_ids: input.skillIds ?? [],
      mcp_connector_ids: input.mcpConnectorIds ?? [],
      model_profile: {},
      instruction: input.instruction ?? "",
      change_note: input.changeNote ?? "",
    }),
  });
}

export function listDigitalEmployeeRevisions(
  employeeId: string,
): Promise<DigitalEmployeeRevision[]> {
  return request(`/api/v1/digital-employees/${employeeId}/revisions`);
}

export function listDigitalEmployeeRouteRules(): Promise<
  DigitalEmployeeRouteRule[]
> {
  return request(
    "/api/v1/digital-employee-route-rules?business_unit_id=bu_demo",
  );
}

export function updateDigitalEmployeeRouteRule(
  employeeId: string,
  input: {
    intents: string[];
    categories: string[];
    channels: string[];
    priority: number;
    fallback: boolean;
    enabled: boolean;
  },
): Promise<DigitalEmployeeRouteRule> {
  return request(`/api/v1/digital-employees/${employeeId}/route-rule`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function listDigitalEmployeeRouteDecisions(): Promise<
  DigitalEmployeeRouteDecisionList
> {
  return request(
    "/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo&limit=100",
  );
}

export function listDigitalEmployeeRouteIntentConflicts(): Promise<DigitalEmployeeRouteIntentConflictList> {
  return request(
    "/api/v1/digital-employee-route-intent-conflicts?business_unit_id=bu_demo",
  );
}

function routeEvaluationQuery(
  serviceEntryId?: string,
  dataset?: DigitalEmployeeRouteEvaluationDataset,
): string {
  const params = new URLSearchParams({
    business_unit_id: "bu_demo",
  });
  if (serviceEntryId) params.set("service_entry_id", serviceEntryId);
  if (dataset) params.set("dataset", dataset);
  return params.toString();
}

export function listDigitalEmployeeRouteEvaluationCases(
  serviceEntryId?: string,
  dataset?: DigitalEmployeeRouteEvaluationDataset,
): Promise<DigitalEmployeeRouteEvaluationCase[]> {
  return request(
    `/api/v1/digital-employee-route-evaluation-cases?${routeEvaluationQuery(serviceEntryId, dataset)}`,
  );
}

export function createDigitalEmployeeRouteEvaluationCase(input: {
  serviceEntryId: string;
  expectedEmployeeId: string;
  dataset?: DigitalEmployeeRouteEvaluationDataset;
  question: string;
  notes?: string;
  enabled?: boolean;
}): Promise<DigitalEmployeeRouteEvaluationCase> {
  return request(
    `/api/v1/digital-employee-route-evaluation-cases?${routeEvaluationQuery()}`,
    {
      method: "POST",
      body: JSON.stringify({
        service_entry_id: input.serviceEntryId,
        expected_employee_id: input.expectedEmployeeId,
        dataset: input.dataset ?? "TUNING",
        question: input.question,
        notes: input.notes ?? "",
        enabled: input.enabled ?? true,
      }),
    },
  );
}

export function updateDigitalEmployeeRouteEvaluationCase(
  caseId: string,
  input: {
    expectedEmployeeId?: string;
    dataset?: DigitalEmployeeRouteEvaluationDataset;
    question?: string;
    notes?: string;
    enabled?: boolean;
  },
): Promise<DigitalEmployeeRouteEvaluationCase> {
  return request(
    `/api/v1/digital-employee-route-evaluation-cases/${caseId}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        expected_employee_id: input.expectedEmployeeId,
        dataset: input.dataset,
        question: input.question,
        notes: input.notes,
        enabled: input.enabled,
      }),
    },
  );
}

export function deleteDigitalEmployeeRouteEvaluationCase(
  caseId: string,
): Promise<void> {
  return request(
    `/api/v1/digital-employee-route-evaluation-cases/${caseId}`,
    { method: "DELETE" },
  );
}

export function runDigitalEmployeeRouteEvaluation(
  serviceEntryId: string,
  dataset: DigitalEmployeeRouteEvaluationDataset = "TUNING",
): Promise<DigitalEmployeeRouteEvaluationRun> {
  return request(
    `/api/v1/digital-employee-route-evaluation-runs?${routeEvaluationQuery(undefined, dataset)}`,
    {
      method: "POST",
      body: JSON.stringify({
        service_entry_id: serviceEntryId,
        dataset,
      }),
    },
  );
}

export function listDigitalEmployeeRouteEvaluationRuns(
  serviceEntryId?: string,
  dataset?: DigitalEmployeeRouteEvaluationDataset,
): Promise<DigitalEmployeeRouteEvaluationRunList> {
  return request(
    `/api/v1/digital-employee-route-evaluation-runs?${routeEvaluationQuery(serviceEntryId, dataset)}&limit=10`,
  );
}

export function planWorkforceTask(input: {
  title: string;
  objective: string;
  context?: Record<string, unknown>;
  supervisorEmployeeId?: string;
}): Promise<WorkforceTask> {
  return request("/api/v1/workforce/tasks", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      title: input.title,
      objective: input.objective,
      context: input.context ?? {},
      supervisor_employee_id: input.supervisorEmployeeId || undefined,
    }),
  });
}

export function listWorkforceTasks(): Promise<WorkforceTaskList> {
  return request("/api/v1/workforce/tasks?business_unit_id=bu_demo");
}

export function executeWorkforceTask(taskId: string): Promise<WorkforceTask> {
  return request(`/api/v1/workforce/tasks/${taskId}/execute`, {
    method: "POST",
  });
}

export function retryWorkforceTask(taskId: string): Promise<WorkforceTask> {
  return request(`/api/v1/workforce/tasks/${taskId}/retry`, {
    method: "POST",
  });
}

export function reassessWorkforceTask(
  taskId: string,
): Promise<WorkforceTask> {
  return request(`/api/v1/workforce/tasks/${taskId}/reassess`, {
    method: "POST",
  });
}

export function createEmployeeDraft(
  taskId: string,
  input: {
    requiredCapability: string;
    name?: string;
  },
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/workforce/tasks/${taskId}/capability-drafts`, {
    method: "POST",
    body: JSON.stringify({
      required_capability: input.requiredCapability,
      name: input.name || undefined,
    }),
  });
}

export function listEmployeeDrafts(): Promise<DigitalEmployeeDraftList> {
  return request(
    "/api/v1/digital-employee-drafts?business_unit_id=bu_demo",
  );
}

export function listEmployeeDraftRevisions(
  draftId: string,
): Promise<DigitalEmployeeDraftRevision[]> {
  return request(
    `/api/v1/digital-employee-drafts/${draftId}/revisions`,
  );
}

export function restoreEmployeeDraftRevision(
  draftId: string,
  revision: number,
): Promise<DigitalEmployeeDraft> {
  return request(
    `/api/v1/digital-employee-drafts/${draftId}/revisions/${revision}/restore`,
    { method: "POST" },
  );
}

export function reviewEmployeeDraft(
  draftId: string,
  input: {
    decision: "APPROVE" | "REJECT";
    note?: string;
  },
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/review`, {
    method: "POST",
    body: JSON.stringify({
      decision: input.decision,
      note: input.note ?? "",
    }),
  });
}

export function updateEmployeeDraft(
  draftId: string,
  input: {
    name?: string;
    capabilities?: string[];
    intents?: string[];
    skillCodes?: string[];
    toolAllowlist?: string[];
  },
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/edit`, {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      capabilities: input.capabilities,
      intents: input.intents,
      skill_codes: input.skillCodes,
      tool_allowlist: input.toolAllowlist,
    }),
  });
}

export function createEmployeeDraftTrial(
  draftId: string,
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/trial`, {
    method: "POST",
  });
}

export function reopenEmployeeDraft(
  draftId: string,
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/reopen`, {
    method: "POST",
  });
}

export function evaluateEmployeeDraft(
  draftId: string,
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/evaluate`, {
    method: "POST",
  });
}

export function publishEmployeeDraft(
  draftId: string,
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/publish`, {
    method: "POST",
  });
}

export function rollbackEmployeeDraft(
  draftId: string,
): Promise<DigitalEmployeeDraft> {
  return request(`/api/v1/digital-employee-drafts/${draftId}/rollback`, {
    method: "POST",
  });
}

export interface CreateDigitalEmployeeInput {
  employee_key: string;
  name: string;
  workflow_key: string;
  handoff_queue: string;
  tools: string[];
  instruction?: string;
}

export function createDigitalEmployee(
  input: CreateDigitalEmployeeInput,
): Promise<DigitalEmployee> {
  const isHr = input.workflow_key === "hr_onboarding_document_collection_v1";
  return request("/api/v1/digital-employees", {
    method: "POST",
    body: JSON.stringify({
      employee_key: input.employee_key,
      name: input.name,
      version: "1.0.0",
      scenario_type: isHr ? "hr_onboarding" : "customer_service_ticket",
      workflow_key: input.workflow_key,
      business_unit_id: "bu_demo",
      service_identity: `digital_employee.${input.employee_key}`,
      handoff_queue: input.handoff_queue,
      knowledge_policy: {
        default_scope: {
          audience: isHr ? "new_employee" : "support_agent",
        },
      },
      model_profile: {},
      tool_allowlist: input.tools,
      instruction: input.instruction ?? "",
    }),
  });
}

export function updateDigitalEmployee(
  employeeId: string,
  input: Record<string, unknown>,
): Promise<DigitalEmployee> {
  return request(`/api/v1/digital-employees/${employeeId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function updateDigitalEmployeeConfiguration(
  employeeId: string,
  input: Record<string, unknown>,
): Promise<DigitalEmployee> {
  return request(
    `/api/v1/digital-employees/${employeeId}/configuration`,
    {
      method: "PUT",
      body: JSON.stringify(input),
    },
  );
}

export function activateDigitalEmployee(
  employeeId: string,
): Promise<DigitalEmployee> {
  return request(`/api/v1/digital-employees/${employeeId}/activate`, {
    method: "POST",
  });
}

export function getToolCalls(limit = 100): Promise<ToolCallList> {
  return request(`/api/v1/tool-calls?limit=${limit}`);
}

export function getToolMetrics(): Promise<ToolMetrics> {
  return request("/api/v1/metrics/tools?business_unit_id=bu_demo");
}

export function getSyncMetrics(): Promise<SyncMetrics> {
  return request("/api/v1/metrics/sync?business_unit_id=bu_demo");
}

export function getModelMetrics(): Promise<ModelMetrics> {
  return request("/api/v1/metrics/models?business_unit_id=bu_demo");
}

export function getModelBudget(employeeId: string): Promise<ModelBudget> {
  return request(`/api/v1/metrics/models/budget?employee_id=${employeeId}`);
}

export function getRagMetrics(): Promise<RagMetrics> {
  return request("/api/v1/metrics/rag?business_unit_id=bu_demo");
}

export function getWorkforceMetrics(): Promise<WorkforceMetrics> {
  return request("/api/v1/metrics/workforce?business_unit_id=bu_demo");
}

export function getRuntimeConfig(): Promise<RuntimeConfig> {
  return request("/api/v1/system/runtime");
}

export function getAgentRuns(limit = 50): Promise<AgentRunList> {
  return request(`/api/v1/agent-runs?business_unit_id=bu_demo&limit=${limit}`);
}

export function getAgentRunTrace(runId: string): Promise<AgentRunTrace> {
  return request(`/api/v1/agent-runs/${runId}/trace`);
}

export function listEcommerceProducts(): Promise<EcommerceProduct[]> {
  return request("/api/v1/ecommerce/products?business_unit_id=bu_demo");
}

export function listEcommerceCategoryProfiles(): Promise<
  EcommerceCategoryProfile[]
> {
  return request("/api/v1/ecommerce/categories?business_unit_id=bu_demo");
}

export function createEcommerceCategoryProfile(input: {
  code: string;
  name: string;
  requiredAttributes: string[];
  presalesKeywords: string[];
  aftersalesKeywords: string[];
  restrictedClaims: string[];
}): Promise<EcommerceCategoryProfile> {
  return request("/api/v1/ecommerce/categories", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      channel: "ecommerce_demo",
      code: input.code,
      name: input.name,
      required_attributes: input.requiredAttributes,
      presales_keywords: input.presalesKeywords,
      aftersales_keywords: input.aftersalesKeywords,
      restricted_claims: input.restrictedClaims,
    }),
  });
}

export async function downloadCategoryImportTemplate(
  profileId: string,
): Promise<Blob> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/ecommerce/categories/${profileId}/import-template`,
    { headers: authHeaders },
  );
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.blob();
}

export function createEcommerceProduct(input: {
  sku: string;
  name: string;
  category: string;
  brand: string;
  price: number;
  attributes: Record<string, unknown>;
}): Promise<EcommerceProduct> {
  return request("/api/v1/ecommerce/products", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      ...input,
    }),
  });
}

export async function downloadEcommerceProductImportTemplate(): Promise<Blob> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/ecommerce/products/import-template`,
    { headers: authHeaders },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.blob();
}

export function previewEcommerceProductImport(
  csv: string,
  categoryProfileId?: string,
): Promise<EcommerceProductImportPreview> {
  const query = new URLSearchParams({ business_unit_id: "bu_demo" });
  if (categoryProfileId) query.set("category_profile_id", categoryProfileId);
  return request(
    `/api/v1/ecommerce/products/import/preview?${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "text/csv; charset=utf-8" },
      body: csv,
    },
  );
}

export function importEcommerceProducts(
  csv: string,
  categoryProfileId?: string,
): Promise<EcommerceProductImportResult> {
  const query = new URLSearchParams({ business_unit_id: "bu_demo" });
  if (categoryProfileId) query.set("category_profile_id", categoryProfileId);
  return request(
    `/api/v1/ecommerce/products/import?${query}`,
    {
      method: "POST",
      headers: { "Content-Type": "text/csv; charset=utf-8" },
      body: csv,
    },
  );
}

export function listEcommerceListings(): Promise<EcommerceListingList> {
  return request("/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo");
}

export function listEcommerceListingBatchJobs(): Promise<EcommerceListingBatchJobList> {
  return request(
    "/api/v1/ecommerce/listing-batch-jobs?business_unit_id=bu_demo&limit=20",
  );
}

export function createEcommerceListingBatchJob(input: {
  productIds: string[];
  channel: string;
  marketCode?: string;
}): Promise<EcommerceListingBatchJob> {
  return request("/api/v1/ecommerce/listing-batch-jobs", {
    method: "POST",
    body: JSON.stringify({
      product_ids: input.productIds,
      channel: input.channel,
      market_code: input.marketCode ?? "CN",
    }),
  });
}

export function getEcommerceMetrics(): Promise<EcommerceOperationalMetrics> {
  return request(
    "/api/v1/ecommerce/metrics?business_unit_id=bu_demo",
  );
}

export function createEcommerceListing(input: {
  productId: string;
  channel: string;
  marketCode: string;
  salePrice?: number;
}): Promise<EcommerceListingDetail> {
  return request("/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo", {
    method: "POST",
    body: JSON.stringify({
      product_id: input.productId,
      channel: input.channel,
      market_code: input.marketCode,
      sale_price: input.salePrice,
    }),
  });
}

export function getEcommerceListing(taskId: string): Promise<EcommerceListingDetail> {
  return request(`/api/v1/ecommerce/listing-tasks/${taskId}`);
}

export async function downloadEcommerceListingPackage(
  taskId: string,
): Promise<Blob> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/ecommerce/listing-tasks/${taskId}/export`,
    { headers: authHeaders },
  );
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(problem?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.blob();
}

export function updateEcommerceListingContent(
  taskId: string,
  expectedVersion: number,
  input: {
    title: string;
    sellingPoints: string[];
    detailDescription: string;
    hashtags: string[];
  },
): Promise<EcommerceListingDetail> {
  return request(`/api/v1/ecommerce/listing-tasks/${taskId}/content`, {
    method: "PATCH",
    body: JSON.stringify({
      expected_version: expectedVersion,
      title: input.title,
      selling_points: input.sellingPoints,
      detail_description: input.detailDescription,
      hashtags: input.hashtags,
    }),
  });
}

export function reviewEcommerceListing(
  taskId: string,
  expectedVersion: number,
  decision: "ACCEPTED" | "REJECTED",
): Promise<{ task_id: string; version: number; status: string; message: string }> {
  return request(`/api/v1/ecommerce/listing-tasks/${taskId}/reviews`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      decision,
      reason_code: "ECOMMERCE_WORKBENCH_REVIEW",
    }),
  });
}

export function listEcommerceProductAssets(
  productId: string,
): Promise<EcommerceProductAsset[]> {
  return request(
    `/api/v1/ecommerce/products/${productId}/assets?business_unit_id=bu_demo`,
  );
}

export async function uploadEcommerceProductAsset(
  productId: string,
  file: File,
): Promise<EcommerceProductAsset> {
  const authHeaders = await getAuthHeaders();
  const query = new URLSearchParams({ filename: file.name });
  const response = await fetch(
    `${API_BASE}/api/v1/ecommerce/products/${productId}/assets?${query}`,
    {
      method: "POST",
      headers: {
        ...authHeaders,
        "Content-Type": file.type || "application/octet-stream",
      },
      body: await file.arrayBuffer(),
    },
  );
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(problem?.detail ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as EcommerceProductAsset;
}

export function generateEcommerceProductImage(
  productId: string,
  prompt: string,
): Promise<EcommerceProductAsset> {
  return request(`/api/v1/ecommerce/products/${productId}/assets/generate`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function generateEcommerceProductImages(
  productId: string,
  prompt: string,
  count: number,
): Promise<{ items: EcommerceProductAsset[] }> {
  return request(
    `/api/v1/ecommerce/products/${productId}/assets/generate-batch`,
    {
      method: "POST",
      body: JSON.stringify({ prompt, count }),
    },
  );
}

export function setPrimaryEcommerceAsset(
  assetId: string,
): Promise<EcommerceProductAsset> {
  return request(`/api/v1/ecommerce/assets/${assetId}/primary`, {
    method: "POST",
  });
}

export function archiveEcommerceAsset(
  assetId: string,
): Promise<EcommerceProductAsset> {
  return request(`/api/v1/ecommerce/assets/${assetId}/archive`, {
    method: "POST",
  });
}

export function acceptEcommerceAssetVisualReview(
  assetId: string,
): Promise<EcommerceProductAsset> {
  return request(
    `/api/v1/ecommerce/assets/${assetId}/visual-review/accept`,
    { method: "POST" },
  );
}

export function retryEcommerceListing(
  taskId: string,
  expectedVersion: number,
): Promise<{ task_id: string; version: number; status: string; message: string }> {
  return request(`/api/v1/ecommerce/listing-tasks/${taskId}/retry`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: expectedVersion,
      reason_code: "ECOMMERCE_MANUAL_RETRY",
    }),
  });
}

export function generateEcommerceStoryboard(
  taskId: string,
): Promise<{ items: EcommerceProductAsset[] }> {
  return request(
    `/api/v1/ecommerce/listing-tasks/${taskId}/storyboard/generate`,
    { method: "POST" },
  );
}

export function renderEcommerceStoryboardVideo(
  taskId: string,
): Promise<EcommerceProductAsset> {
  return request(
    `/api/v1/ecommerce/listing-tasks/${taskId}/storyboard/video`,
    { method: "POST" },
  );
}

export function createEcommerceVideoRenderJob(
  taskId: string,
  input?: {
    backgroundMusicAssetId?: string;
    backgroundMusicVolume?: number;
  },
): Promise<EcommerceVideoRenderJob> {
  return request(
    `/api/v1/ecommerce/listing-tasks/${taskId}/storyboard/video-jobs`,
    {
      method: "POST",
      body: JSON.stringify({
        background_music_asset_id: input?.backgroundMusicAssetId ?? null,
        background_music_volume: input?.backgroundMusicVolume ?? 0.18,
      }),
    },
  );
}

export function listEcommerceVideoRenderJobs(
  taskId: string,
): Promise<EcommerceVideoRenderJobList> {
  return request(
    `/api/v1/ecommerce/listing-tasks/${taskId}/video-render-jobs?limit=20`,
  );
}

export function retryEcommerceVideoRenderJob(
  jobId: string,
): Promise<EcommerceVideoRenderJob> {
  return request(`/api/v1/ecommerce/video-render-jobs/${jobId}/retry`, {
    method: "POST",
  });
}

export function listEcommerceImageGenerations(): Promise<EcommerceImageGenerationList> {
  return request(
    "/api/v1/ecommerce/image-generations?business_unit_id=bu_demo&limit=50",
  );
}

export async function fetchEcommerceAssetBlob(
  assetId: string,
): Promise<Blob> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(
    `${API_BASE}/api/v1/ecommerce/assets/${assetId}/content`,
    { headers: authHeaders },
  );
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.blob();
}

export function takeOverTicket(id: string, version: number): Promise<unknown> {
  return request(`/api/v1/tickets/${id}/takeover`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: version,
      reason_code: "AGENT_REQUESTED",
      note: "从数字员工工作台接管",
    }),
  });
}

export function reviewTicket(
  id: string,
  version: number,
  decision:
    | "ACCEPTED"
    | "EDITED_AND_ACCEPTED"
    | "REJECTED"
    | "ESCALATED",
  editedText?: string,
  reasonCode?: string,
): Promise<unknown> {
  return request(`/api/v1/tickets/${id}/reviews`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: version,
      decision,
      edited_text: editedText,
      reason_code:
        reasonCode ??
        (decision === "REJECTED"
          ? "AGENT_REJECTED"
          : decision === "ESCALATED"
            ? "AGENT_ESCALATED"
            : "AGENT_APPROVED"),
    }),
  });
}

export function retryTicketSync(id: string, version: number): Promise<unknown> {
  return request(`/api/v1/tickets/${id}/sync-attempts`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: version,
      reason_code: "MANUAL_SYNC_RETRY",
    }),
  });
}

export function listKnowledgeSpaces(): Promise<KnowledgeSpace[]> {
  return request("/api/v1/knowledge-spaces?business_unit_id=bu_demo");
}

export function syncProductKnowledgeCards(
  productIds: string[] = [],
): Promise<ProductKnowledgeSyncResult> {
  return request("/api/v1/knowledge/product-sync", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      product_ids: productIds,
    }),
  });
}

export function listKnowledgeEvaluationCases(
  dataset: KnowledgeEvaluationDataset = "TUNING",
): Promise<KnowledgeEvaluationCase[]> {
  const suffix = dataset === "TUNING" ? "" : `&dataset=${dataset}`;
  return request(
    `/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo${suffix}`,
  );
}

export function createKnowledgeEvaluationCase(input: {
  name: string;
  query: string;
  knowledgeSpaceId: string;
  dataset: KnowledgeEvaluationDataset;
  expectedTitles: string[];
  expectedChunkIds: string[];
  expectedPassages?: { documentId: string; text: string }[];
  expectedDocumentIds: string[];
  negativeDocumentIds: string[];
  expectNoGrounding: boolean;
  scope: Record<string, string>;
}): Promise<KnowledgeEvaluationCase> {
  return request("/api/v1/knowledge/evaluation-cases", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      knowledge_space_id: input.knowledgeSpaceId,
      employee_id: null,
      name: input.name,
      query: input.query,
      dataset: input.dataset,
      expected_titles: input.expectedTitles,
      expected_chunk_ids: input.expectedChunkIds,
      expected_passages: (input.expectedPassages ?? []).map((passage) => ({
        document_id: passage.documentId,
        text: passage.text,
      })),
      expected_document_ids: input.expectedDocumentIds,
      negative_document_ids: input.negativeDocumentIds,
      expect_no_grounding: input.expectNoGrounding,
      scope: input.scope,
    }),
  });
}

export function updateKnowledgeEvaluationCase(
  caseId: string,
  enabled: boolean,
): Promise<KnowledgeEvaluationCase> {
  return request(`/api/v1/knowledge/evaluation-cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export function runKnowledgeEvaluation(
  knowledgeSpaceId?: string,
  dataset: KnowledgeEvaluationDataset = "TUNING",
): Promise<KnowledgeEvaluationRun> {
  return request("/api/v1/knowledge/evaluation-runs", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      knowledge_space_id: knowledgeSpaceId || null,
      dataset,
      top_k: 5,
      min_recall_at_k: 0.8,
      min_mrr: 0.6,
      min_no_grounding_accuracy: 0.8,
    }),
  });
}

export function listKnowledgeEvaluationRuns(
  dataset: KnowledgeEvaluationDataset = "TUNING",
): Promise<KnowledgeEvaluationRunList> {
  const suffix = dataset === "TUNING" ? "" : `&dataset=${dataset}`;
  return request(
    `/api/v1/knowledge/evaluation-runs?business_unit_id=bu_demo&limit=10${suffix}`,
  );
}

export function listKnowledgeRepairTasks(): Promise<KnowledgeRepairTaskList> {
  return request(
    "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo",
  );
}

export function getAnswerQualitySummary(
  days = 30,
): Promise<AnswerQualitySummary> {
  return request(
    `/api/v1/knowledge/answer-evaluations/summary?business_unit_id=bu_demo&days=${days}`,
  );
}

export function listAnswerQualitySamples(
  days = 30,
  limit = 10,
): Promise<AnswerQualitySampleList> {
  return request(
    `/api/v1/knowledge/answer-evaluations/samples?business_unit_id=bu_demo&days=${days}&limit=${limit}`,
  );
}

export function recordAnswerQualityEvaluation(input: {
  draftId: string;
  verdict: AnswerQualityVerdict;
  hallucinated: boolean;
  note?: string;
}): Promise<AnswerQualityEvaluation> {
  return request("/api/v1/knowledge/answer-evaluations", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      draft_id: input.draftId,
      verdict: input.verdict,
      hallucinated: input.hallucinated,
      note: input.note || null,
    }),
  });
}

export function listKnowledgeFeedback(): Promise<KnowledgeFeedbackList> {
  return request("/api/v1/knowledge/feedback?business_unit_id=bu_demo");
}

export function listKnowledgeFeedbackClusters(): Promise<KnowledgeFeedbackClusterList> {
  return request(
    "/api/v1/knowledge/feedback/clusters?business_unit_id=bu_demo",
  );
}

export function updateKnowledgeRepairTask(
  taskId: string,
  input: {
    status?: string;
    assigneeId?: string;
    resolutionNote?: string;
  },
): Promise<KnowledgeRepairTask> {
  return request(`/api/v1/knowledge/repair-tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: input.status,
      assignee_id: input.assigneeId,
      resolution_note: input.resolutionNote,
    }),
  });
}

export function verifyKnowledgeRepairTask(
  taskId: string,
): Promise<KnowledgeRepairTask> {
  return request(`/api/v1/knowledge/repair-tasks/${taskId}/verify`, {
    method: "POST",
  });
}

export function createKnowledgeSpace(input: {
  code: string;
  name: string;
  description: string;
  domain?: string;
  channel?: string;
  category?: string;
  workflowKey?: string;
  evaluationRequired?: boolean;
  categoryProfileId?: string;
}): Promise<KnowledgeSpace> {
  return request("/api/v1/knowledge-spaces", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      code: input.code,
      name: input.name,
      description: input.description,
      domain: input.domain ?? "ecommerce",
      channel: input.channel || null,
      category: input.category || null,
      category_profile_id: input.categoryProfileId || null,
      workflow_key: input.workflowKey || null,
      owner_id: "demo.agent",
      evaluation_required: input.evaluationRequired ?? false,
    }),
  });
}

export function updateKnowledgeSpace(
  spaceId: string,
  input: Record<string, unknown>,
): Promise<KnowledgeSpace> {
  return request(`/api/v1/knowledge-spaces/${spaceId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function listEmployeeKnowledgeBindings(
  employeeId: string,
): Promise<EmployeeKnowledgeBinding[]> {
  return request(
    `/api/v1/digital-employees/${employeeId}/knowledge-bindings`,
  );
}

export function listAgentSkills(): Promise<AgentSkill[]> {
  return request("/api/v1/skills?business_unit_id=bu_demo");
}

export function createAgentSkill(input: {
  code: string;
  name: string;
  description: string;
  instructions: string;
  triggers: string[];
  tools: string[];
  status?: string;
}): Promise<AgentSkill> {
  return request("/api/v1/skills", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      ...input,
      status: input.status ?? "ACTIVE",
    }),
  });
}

export function updateAgentSkill(
  skillId: string,
  input: Partial<{
    name: string;
    description: string;
    instructions: string;
    triggers: string[];
    tools: string[];
    status: string;
  }>,
): Promise<AgentSkill> {
  return request(`/api/v1/skills/${skillId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function listEmployeeSkills(
  employeeId: string,
): Promise<EmployeeSkillBinding[]> {
  return request(`/api/v1/digital-employees/${employeeId}/skills`);
}

export function replaceEmployeeSkills(
  employeeId: string,
  bindings: Array<{
    skillId: string;
    enabled?: boolean;
    priority?: number;
  }>,
): Promise<EmployeeSkillBinding[]> {
  return request(`/api/v1/digital-employees/${employeeId}/skills`, {
    method: "PUT",
    body: JSON.stringify({
      bindings: bindings.map((binding) => ({
        skill_id: binding.skillId,
        enabled: binding.enabled ?? true,
        priority: binding.priority ?? 100,
      })),
    }),
  });
}

export function listMcpConnectors(): Promise<McpConnector[]> {
  return request("/api/v1/mcp/connectors?business_unit_id=bu_demo");
}

export function createMcpConnector(input: {
  code: string;
  name: string;
  description: string;
  url: string;
  headerEnv: Record<string, string>;
  timeoutSeconds?: number;
  status?: string;
}): Promise<McpConnector> {
  return request("/api/v1/mcp/connectors", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      code: input.code,
      name: input.name,
      description: input.description,
      transport: "streamable_http",
      url: input.url,
      header_env: input.headerEnv,
      timeout_seconds: input.timeoutSeconds ?? 30,
      status: input.status ?? "ACTIVE",
    }),
  });
}

export function updateMcpConnector(
  connectorId: string,
  input: Partial<{
    name: string;
    description: string;
    url: string;
    headerEnv: Record<string, string>;
    timeoutSeconds: number;
    status: string;
  }>,
): Promise<McpConnector> {
  return request(`/api/v1/mcp/connectors/${connectorId}`, {
    method: "PATCH",
    body: JSON.stringify({
      ...(input.name !== undefined ? { name: input.name } : {}),
      ...(input.description !== undefined
        ? { description: input.description }
        : {}),
      ...(input.url !== undefined ? { url: input.url } : {}),
      ...(input.headerEnv !== undefined
        ? { header_env: input.headerEnv }
        : {}),
      ...(input.timeoutSeconds !== undefined
        ? { timeout_seconds: input.timeoutSeconds }
        : {}),
      ...(input.status !== undefined ? { status: input.status } : {}),
    }),
  });
}

export function discoverMcpConnector(connectorId: string): Promise<McpHealth> {
  return request(`/api/v1/mcp/connectors/${connectorId}/discover`, {
    method: "POST",
  });
}

export function listEmployeeMcpConnectors(
  employeeId: string,
): Promise<EmployeeMcpBinding[]> {
  return request(`/api/v1/digital-employees/${employeeId}/mcp-connectors`);
}

export function replaceEmployeeMcpConnectors(
  employeeId: string,
  bindings: Array<{
    connectorId: string;
    enabled?: boolean;
    allowedTools?: string[];
    writeApproved?: boolean;
  }>,
): Promise<EmployeeMcpBinding[]> {
  return request(`/api/v1/digital-employees/${employeeId}/mcp-connectors`, {
    method: "PUT",
    body: JSON.stringify({
      bindings: bindings.map((binding) => ({
        connector_id: binding.connectorId,
        enabled: binding.enabled ?? true,
        allowed_tools: binding.allowedTools ?? [],
        write_approved: binding.writeApproved ?? false,
      })),
    }),
  });
}

export function listMcpToolApprovals(
  status?: string,
): Promise<McpToolApprovalList> {
  const query = new URLSearchParams({
    business_unit_id: "bu_demo",
    limit: "100",
  });
  if (status) query.set("status", status);
  return request(`/api/v1/mcp/tool-approvals?${query.toString()}`);
}

export function decideMcpToolApproval(
  approvalId: string,
  input: {
    decision: "APPROVE" | "REJECT";
    expectedVersion: number;
    note: string;
  },
): Promise<McpToolApproval> {
  return request(`/api/v1/mcp/tool-approvals/${approvalId}/decisions`, {
    method: "POST",
    body: JSON.stringify({
      decision: input.decision,
      expected_version: input.expectedVersion,
      note: input.note,
    }),
  });
}

export function listMcpActionIncidents(
  status?: string,
): Promise<McpActionIncidentList> {
  const query = new URLSearchParams({
    business_unit_id: "bu_demo",
    limit: "100",
  });
  if (status) query.set("status", status);
  return request(`/api/v1/mcp/action-incidents?${query.toString()}`);
}

export function actOnMcpActionIncident(
  incidentId: string,
  action: "acknowledge" | "resolve",
  input: {
    expectedVersion: number;
    note: string;
    outcome?:
      | "EXECUTED_AS_INTENDED"
      | "NOT_EXECUTED"
      | "EXECUTED_INCORRECTLY"
      | "INCONCLUSIVE";
  },
): Promise<McpActionIncident> {
  return request(
    `/api/v1/mcp/action-incidents/${incidentId}/${action}`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        note: input.note,
        ...(action === "resolve"
          ? { outcome: input.outcome ?? "INCONCLUSIVE" }
          : {}),
      }),
    },
  );
}

export function reconcileMcpActionIncident(
  incidentId: string,
  input: {
    expectedVersion: number;
    toolId?: string;
  },
): Promise<McpActionIncident> {
  return request(`/api/v1/mcp/action-incidents/${incidentId}/reconcile`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: input.expectedVersion,
      tool_id: input.toolId || undefined,
    }),
  });
}

export function requestMcpActionCompensation(
  incidentId: string,
  input: {
    expectedVersion: number;
    toolId?: string;
    arguments: Record<string, unknown>;
    note: string;
  },
): Promise<McpActionIncident> {
  return request(
    `/api/v1/mcp/action-incidents/${incidentId}/compensation-requests`,
    {
      method: "POST",
      body: JSON.stringify({
        expected_version: input.expectedVersion,
        tool_id: input.toolId || undefined,
        arguments: input.arguments,
        note: input.note,
      }),
    },
  );
}

export function replaceEmployeeKnowledgeBindings(
  employeeId: string,
  bindings: Array<{
    knowledgeSpaceId: string;
    workflowKey?: string | null;
    scope?: Record<string, unknown>;
    enabled?: boolean;
  }>,
): Promise<EmployeeKnowledgeBinding[]> {
  return request(
    `/api/v1/digital-employees/${employeeId}/knowledge-bindings`,
    {
      method: "PUT",
      body: JSON.stringify({
        bindings: bindings.map((binding) => ({
          knowledge_space_id: binding.knowledgeSpaceId,
          workflow_key: binding.workflowKey ?? null,
          scope: binding.scope ?? {},
          enabled: binding.enabled ?? true,
        })),
      }),
    },
  );
}

export function listKnowledgeDocuments(
  spaceId?: string,
): Promise<KnowledgeDocument[]> {
  const query = new URLSearchParams({ business_unit_id: "bu_demo" });
  if (spaceId) query.set("space_id", spaceId);
  return request(`/api/v1/knowledge-documents?${query}`);
}

export function listKnowledgeVersions(
  documentId: string,
): Promise<KnowledgeVersion[]> {
  return request(`/api/v1/knowledge-documents/${documentId}/versions`);
}

export function createKnowledgeDocument(input: {
  title: string;
  docType: string;
  spaceId?: string;
  scope?: Record<string, unknown>;
}): Promise<KnowledgeDocument> {
  return request("/api/v1/knowledge-documents", {
    method: "POST",
    body: JSON.stringify({
      business_unit_id: "bu_demo",
      space_id: input.spaceId || null,
      title: input.title,
      doc_type: input.docType,
      owner_id: "demo.agent",
      scope: input.scope ?? {},
    }),
  });
}

export function updateKnowledgeDocument(
  documentId: string,
  input: {
    title: string;
    docType: string;
    spaceId?: string;
    scope?: Record<string, unknown>;
  },
): Promise<KnowledgeDocument> {
  return request(`/api/v1/knowledge-documents/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify({
      title: input.title,
      doc_type: input.docType,
      space_id: input.spaceId || null,
      scope: input.scope ?? {},
    }),
  });
}

export function archiveKnowledgeDocument(
  documentId: string,
): Promise<KnowledgeDocument> {
  return request(`/api/v1/knowledge-documents/${documentId}/archive`, {
    method: "POST",
  });
}

export function restoreKnowledgeDocument(
  documentId: string,
): Promise<KnowledgeDocument> {
  return request(`/api/v1/knowledge-documents/${documentId}/restore`, {
    method: "POST",
  });
}

export function createKnowledgeVersion(
  documentId: string,
  versionLabel: string,
  content: string,
): Promise<KnowledgeVersion> {
  return request(`/api/v1/knowledge-documents/${documentId}/versions`, {
    method: "POST",
    body: JSON.stringify({
      version_label: versionLabel,
      content,
      effective_from: new Date().toISOString(),
    }),
  });
}

export async function uploadKnowledgeVersion(
  documentId: string,
  versionLabel: string,
  file: File,
): Promise<{ version_id: string; status: string }> {
  const authHeaders = await getAuthHeaders();
  const query = new URLSearchParams({
    version_label: versionLabel,
    filename: file.name,
  });
  const response = await fetch(
    `${API_BASE}/api/v1/knowledge-documents/${documentId}/uploads?${query}`,
    {
      method: "POST",
      headers: {
        ...authHeaders,
        "Content-Type": file.type || "application/octet-stream",
      },
      body: await file.arrayBuffer(),
    },
  );
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(problem?.detail ?? `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as { version_id: string; status: string };
}

export function publishKnowledgeVersion(
  documentId: string,
  versionId: string,
): Promise<KnowledgeVersion> {
  return request(
    `/api/v1/knowledge-documents/${documentId}/versions/${versionId}/publish`,
    {
      method: "POST",
      body: JSON.stringify({ release_note: "Published from workbench" }),
    },
  );
}

export function searchKnowledge(
  query: string,
  options?: {
    spaceId?: string;
    employeeId?: string;
    scope?: Record<string, string>;
  },
): Promise<{
  items: KnowledgeHit[];
  embedding_model: string;
  reranker: string;
  retrieval_mode?: "dense" | "hybrid";
}> {
  return request("/api/v1/knowledge/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      business_unit_id: "bu_demo",
      space_id: options?.spaceId || null,
      employee_id: options?.employeeId || null,
      scope: options?.scope ?? {},
      top_k: 5,
    }),
  });
}

