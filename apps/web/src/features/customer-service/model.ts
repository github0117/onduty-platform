import { getActiveBusinessUnitId } from "../../auth";
import { humanReasonLabels, localizedLabel } from "../../statusLabels";
import type { ConversationHandoff, TicketDetail } from "../../types";

// Why a conversation left its previous employee. Keep in sync with
// HANDOFF_REASONS in apps/api/src/ticket_agent/customer_service/handoffs.py.
export const REROUTE_REASON_LABELS: Record<string, string> = {
  EXPLICIT_REQUEST: "客户明确要求转接",
  CAPABILITY_GAP: "当前员工不具备该问题能力",
  TOPIC_CHANGED: "工单已结束，话题已切换",
  SUSTAINED_TOPIC: "连续多轮指向同一员工",
  ENTRY_SCOPE_CHANGED: "入口员工范围调整",
  MANUAL: "人工交接",
  ESCALATION: "升级处理",
};

export function handoffHeadline(handoff: ConversationHandoff): string {
  if (handoff.kind === "AUTO_REROUTE") {
    return `系统自动转接：${handoff.from_employee_name ?? "数字员工"} → ${
      handoff.to_employee_name ?? "接手员工"
    }`;
  }
  if (handoff.kind === "HUMAN_TAKEOVER") {
    return `人工接管：${handoff.from_employee_name ?? "数字员工"} → 人工`;
  }
  if (handoff.kind === "HUMAN_RETURN") {
    return `人工交还：人工 → ${handoff.to_employee_name ?? "数字员工"}`;
  }
  return `由 ${handoff.from_employee_name ?? "数字员工"} 交接给 ${
    handoff.to_employee_name ?? "接手员工"
  }`;
}

export const categoryLabels: Record<string, string> = {
  ecommerce_presales: "售前咨询",
  ecommerce_aftersales: "售后服务",
  enterprise_service_request: "企业服务请求",
  it_support: "IT 支持",
  hr_service: "HR 服务",
  finance_service: "财务服务",
  other_unclassified: "待分类",
};

export const riskLevels = [
  { code: "R0", label: "低风险", description: "售前咨询，可按策略自动回复", color: "green" },
  { code: "R1", label: "一般风险", description: "一般业务风险，按流程审核", color: "gold" },
  { code: "R2", label: "高敏风险", description: "资金、投诉或隐私，强制人工", color: "volcano" },
  { code: "R3", label: "重大风险", description: "安全事件，进入应急响应", color: "red" },
] as const;

export type ConversationFilter =
  | "all"
  | "review"
  | "human"
  | "mine"
  | "completed";

export type CustomerServiceViewMode = "guide" | "workspace" | "admin";
export type CustomerServiceSurfaceMode = CustomerServiceViewMode | "chat";
export type CustomerDemoScenario = "enterprise" | "ecommerce";

export type CustomerServiceSection =
  | "chat"
  | "workbench"
  | "admin"
  | "approvals"
  | "incidents"
  | "scheduling";

export function riskColor(level: string | null): string {
  return riskLevels.find((item) => item.code === level)?.color ?? "default";
}

export function workflowColor(state: string): string {
  if (state === "NEEDS_HUMAN" || state === "FAILED_TERMINAL") return "red";
  if (state === "PENDING_REVIEW") return "gold";
  if (state === "TAKEN_OVER") return "purple";
  if (state === "COMPLETED") return "green";
  if (state === "FAILED_RETRYABLE") return "volcano";
  return "blue";
}

export function ticketOutcome(ticket: TicketDetail): {
  color: string;
  title: string;
  reason: string;
  nextStep: string;
} {
  const humanReason = localizedLabel(
    humanReasonLabels,
    ticket.routing.human_reason,
    "该问题需要人工判断或审批",
  );
  if (
    ticket.workflow_state === "NEEDS_HUMAN" ||
    ticket.routing.needs_human
  ) {
    return {
      color: "orange",
      title: "需要人工介入",
      reason: humanReason,
      nextStep: "请查看建议和证据，接管会话后由人工确认或审批。",
    };
  }
  if (ticket.workflow_state === "TAKEN_OVER") {
    return {
      color: "purple",
      title: "人工正在处理",
      reason: "会话已由人工客服接管，数字员工负责提供知识和工具结果。",
      nextStep: "继续核实买家诉求并发送人工回复。",
    };
  }
  if (
    ticket.draft?.status === "AUTO_ACCEPTED" ||
    (ticket.workflow_state === "COMPLETED" &&
      ticket.risk?.level === "R0")
  ) {
    return {
      color: "green",
      title: "数字员工已自动处理",
      reason:
        "这是低风险售前问题，回答具有企业知识依据，且没有触发退款、隐私或承诺类限制。",
      nextStep: "查看最终回复；如果买家继续追问，系统会重新判断。",
    };
  }
  if (ticket.draft) {
    return {
      color: "blue",
      title: "回答已生成，等待确认",
      reason:
        ticket.risk?.level && ticket.risk.level !== "R0"
          ? `该问题属于 ${ticket.risk.level} 风险，数字员工不能直接对客发送。`
          : "当前回答没有满足自动发送的全部条件，需要人工确认。",
      nextStep: "审核并必要时修改回答，确认后再发送给买家。",
    };
  }
  return {
    color: "default",
    title: "正在分析",
    reason: "系统正在识别问题、检索知识或查询业务系统。",
    nextStep: "稍候刷新；如果长时间没有结果，请检查接口或转人工。",
  };
}

export interface ConversationTurn {
  role: "BUYER" | "ASSISTANT";
  text: string;
}

export type HistoryScope = "current" | "all";

export interface StoredSandboxState {
  employeeId: string;
  subject: string;
  body: string;
  ticketId: string;
  editedText: string;
  history: ConversationTurn[];
  conversationId?: string;
  categoryProfileId?: string;
  productId?: string;
}

export const sandboxStorageKey = "digital-workforce:customer-service-sandbox:v2";
export const viewModeStorageKey = "digital-workforce:customer-service-view-mode:v2";
export const chatStateStoragePrefix = "digital-workforce:customer-chat-demo:v2";

export const approvalStatusLabels: Record<string, string> = {
  PENDING: "等待审批",
  EXECUTING: "执行中",
  SUCCEEDED: "执行成功",
  REJECTED: "审批拒绝",
  FAILED: "执行失败",
};

export function approvalStatusColor(status: string): string {
  if (status === "PENDING") return "gold";
  if (status === "EXECUTING") return "blue";
  if (status === "SUCCEEDED") return "green";
  if (status === "REJECTED") return "default";
  return "red";
}

export const incidentStatusLabels: Record<string, string> = {
  OPEN: "待处理",
  ACKNOWLEDGED: "处理中",
  RESOLVED: "已关闭",
};

export const incidentFailureLabels: Record<string, string> = {
  EXECUTION_UNKNOWN: "外部结果不确定",
  REMOTE_REJECTED: "外部系统拒绝",
  PRE_EXECUTION: "执行前失败",
};

export const reconciliationStatusLabels: Record<string, string> = {
  NOT_REQUESTED: "尚未对账",
  SUCCEEDED: "对账已返回",
  FAILED: "对账失败",
};

export const compensationStatusLabels: Record<string, string> = {
  NOT_REQUESTED: "无需补偿",
  PENDING_APPROVAL: "补偿待审批",
  EXECUTING: "补偿执行中",
  SUCCEEDED: "补偿成功",
  FAILED: "补偿失败",
};

export function loadSandboxState(): StoredSandboxState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(sandboxStorageKey);
    return raw ? (JSON.parse(raw) as StoredSandboxState) : null;
  } catch {
    return null;
  }
}

export interface StoredChatDemoState {
  conversationId?: string;
  ticketId?: string;
}

export function getChatDemoStorageKey(
  scenario: CustomerDemoScenario,
  actorKey: string,
): string {
  return [
    chatStateStoragePrefix,
    getActiveBusinessUnitId(),
    actorKey,
    scenario,
  ].join(":");
}

export function loadChatDemoState(
  scenario: CustomerDemoScenario,
  actorKey: string,
): StoredChatDemoState {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(
      getChatDemoStorageKey(scenario, actorKey),
    );
    return raw ? (JSON.parse(raw) as StoredChatDemoState) : {};
  } catch {
    return {};
  }
}
