import {
  Alert,
  Avatar,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Form,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Skeleton,
  Space,
  Statistic,
  Steps,
  Tabs,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import {
  ApiError,
  actOnMcpActionIncident,
  addCustomerConversationMessage,
  acknowledgeCustomerServiceNotification,
  autoAssignCustomerConversations,
  createCustomerConversation,
  createKnowledgeFeedback,
  decideMcpToolApproval,
  generateCustomerReplySuggestion,
  getCustomerConversation,
  getCustomerAssignmentQueue,
  getCustomerServiceMetrics,
  getCustomerServiceHistoryMetrics,
  getRuntimeConfig,
  getTicket,
  heartbeatCustomerAgent,
  listEcommerceProducts,
  listCustomerAgentPresence,
  listCustomerServiceAlerts,
  listCustomerServiceNotifications,
  listDigitalEmployees,
  listDigitalEmployeeRouteDecisions,
  listEcommerceCategoryProfiles,
  listEmployeeKnowledgeBindings,
  listCustomerConversations,
  listBusinessServiceEntries,
  listKnowledgeSpaces,
  listMcpToolApprovals,
  listMcpActionIncidents,
  optimizeCustomerReply,
  queryLogistics,
  reconcileMcpActionIncident,
  releaseCustomerConversation,
  reviewTicket,
  requestMcpActionCompensation,
  sendManualCustomerReply,
  streamCustomerConversationMessage,
  takeOverCustomerConversation,
  watchCustomerConversation,
} from "./api";
import EmployeeProfileDrawer from "./EmployeeProfileDrawer";
import type {
  AssignmentRunResult,
  CustomerConversation,
  CustomerReplySuggestion,
  McpActionIncident,
  McpToolApproval,
  TicketDetail,
} from "./types";
import { message } from "./feedback";
import { getActiveBusinessUnitId, getActiveTestIdentity } from "./auth";
import {
  conversationStatusLabels,
  draftStateLabels,
  groundingStatusLabels,
  humanReasonLabels,
  localizedLabel,
  providerLabels,
  queueLabels,
  workflowStateLabels,
} from "./statusLabels";
import CustomerServiceWorkbench from "./CustomerServiceWorkbench";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;
const terminalStates = new Set(["COMPLETED", "FAILED_TERMINAL"]);

const categoryLabels: Record<string, string> = {
  ecommerce_presales: "售前咨询",
  ecommerce_aftersales: "售后服务",
  enterprise_service_request: "企业服务请求",
  it_support: "IT 支持",
  hr_service: "HR 服务",
  finance_service: "财务服务",
  other_unclassified: "待分类",
};

const riskLevels = [
  { code: "R0", label: "低风险", description: "售前咨询，可按策略自动回复", color: "green" },
  { code: "R1", label: "一般风险", description: "一般业务风险，按流程审核", color: "gold" },
  { code: "R2", label: "高敏风险", description: "资金、投诉或隐私，强制人工", color: "volcano" },
  { code: "R3", label: "重大风险", description: "安全事件，进入应急响应", color: "red" },
] as const;

type ConversationFilter =
  | "all"
  | "review"
  | "human"
  | "mine"
  | "completed";

type CustomerServiceViewMode = "guide" | "workspace" | "admin";
type CustomerServiceSurfaceMode = CustomerServiceViewMode | "chat";
type CustomerDemoScenario = "enterprise" | "ecommerce";

export type CustomerServiceSection =
  | "chat"
  | "workbench"
  | "admin"
  | "approvals"
  | "incidents";

function riskColor(level: string | null): string {
  return riskLevels.find((item) => item.code === level)?.color ?? "default";
}

function workflowColor(state: string): string {
  if (state === "NEEDS_HUMAN" || state === "FAILED_TERMINAL") return "red";
  if (state === "PENDING_REVIEW") return "gold";
  if (state === "TAKEN_OVER") return "purple";
  if (state === "COMPLETED") return "green";
  if (state === "FAILED_RETRYABLE") return "volcano";
  return "blue";
}

function ticketOutcome(ticket: TicketDetail): {
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

interface ConversationTurn {
  role: "BUYER" | "ASSISTANT";
  text: string;
}

type HistoryScope = "current" | "all";

interface StoredSandboxState {
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

const sandboxStorageKey = "digital-workforce:customer-service-sandbox:v2";
const viewModeStorageKey = "digital-workforce:customer-service-view-mode:v2";
const chatStateStoragePrefix = "digital-workforce:customer-chat-demo:v2";

const approvalStatusLabels: Record<string, string> = {
  PENDING: "等待审批",
  EXECUTING: "执行中",
  SUCCEEDED: "执行成功",
  REJECTED: "审批拒绝",
  FAILED: "执行失败",
};

function approvalStatusColor(status: string): string {
  if (status === "PENDING") return "gold";
  if (status === "EXECUTING") return "blue";
  if (status === "SUCCEEDED") return "green";
  if (status === "REJECTED") return "default";
  return "red";
}

const incidentStatusLabels: Record<string, string> = {
  OPEN: "待处理",
  ACKNOWLEDGED: "处理中",
  RESOLVED: "已关闭",
};

const incidentFailureLabels: Record<string, string> = {
  EXECUTION_UNKNOWN: "外部结果不确定",
  REMOTE_REJECTED: "外部系统拒绝",
  PRE_EXECUTION: "执行前失败",
};

const reconciliationStatusLabels: Record<string, string> = {
  NOT_REQUESTED: "尚未对账",
  SUCCEEDED: "对账已返回",
  FAILED: "对账失败",
};

const compensationStatusLabels: Record<string, string> = {
  NOT_REQUESTED: "无需补偿",
  PENDING_APPROVAL: "补偿待审批",
  EXECUTING: "补偿执行中",
  SUCCEEDED: "补偿成功",
  FAILED: "补偿失败",
};

function loadSandboxState(): StoredSandboxState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(sandboxStorageKey);
    return raw ? (JSON.parse(raw) as StoredSandboxState) : null;
  } catch {
    return null;
  }
}

interface StoredChatDemoState {
  conversationId?: string;
  ticketId?: string;
}

function getChatDemoStorageKey(scenario: CustomerDemoScenario): string {
  return [
    chatStateStoragePrefix,
    getActiveBusinessUnitId(),
    getActiveTestIdentity().id,
    scenario,
  ].join(":");
}

function loadChatDemoState(
  scenario: CustomerDemoScenario,
): StoredChatDemoState {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(
      getChatDemoStorageKey(scenario),
    );
    return raw ? (JSON.parse(raw) as StoredChatDemoState) : {};
  } catch {
    return {};
  }
}

function CustomerChatDemo({
  technicalMode,
  scenario,
  onOpenWorkspace,
  onOpenAdmin,
}: {
  technicalMode: boolean;
  scenario: CustomerDemoScenario;
  onOpenWorkspace: (conversationId?: string) => void;
  onOpenAdmin?: () => void;
}) {
  const queryClient = useQueryClient();
  const chatStateStorageKey = getChatDemoStorageKey(scenario);
  const requestedConversationId =
    new URLSearchParams(window.location.search).get("conversation") ?? "";
  const [stored] = useState(() => loadChatDemoState(scenario));
  const [conversationId, setConversationId] = useState(
    requestedConversationId || stored.conversationId || "",
  );
  const [ticketId, setTicketId] = useState(
    requestedConversationId ? "" : stored.ticketId ?? "",
  );
  const [input, setInput] = useState("");
  const [pendingBuyerText, setPendingBuyerText] = useState("");
  const [liveReply, setLiveReply] = useState<{
    conversationId: string;
    turnId: string | null;
    text: string;
    stage: string;
  } | null>(null);
  const liveConversationRef = useRef<string | null>(null);
  const minConversationVersionRef = useRef(0);
  const [editingReview, setEditingReview] = useState(false);
  const [reviewDraftText, setReviewDraftText] = useState("");
  const [manualSuggestion, setManualSuggestion] =
    useState<CustomerReplySuggestion | null>(null);
  const [manualSuggestionError, setManualSuggestionError] = useState("");
  const [profileEmployeeId, setProfileEmployeeId] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const categories = useQuery({
    queryKey: ["ecommerce-categories"],
    queryFn: listEcommerceCategoryProfiles,
    enabled: scenario === "ecommerce",
  });
  const products = useQuery({
    queryKey: ["ecommerce-products"],
    queryFn: listEcommerceProducts,
    enabled: scenario === "ecommerce",
  });
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
  });
  const serviceEntries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
  });
  const conversation = useQuery({
    queryKey: ["chat-demo-conversation", conversationId],
    queryFn: () => getCustomerConversation(conversationId),
    enabled: Boolean(conversationId),
    refetchInterval: 12_000,
    refetchIntervalInBackground: false,
  });
  const ticket = useQuery({
    queryKey: ["chat-demo-ticket", ticketId],
    queryFn: () => getTicket(ticketId),
    enabled: Boolean(ticketId),
    refetchInterval: (query) =>
      terminalStates.has(query.state.data?.workflow_state ?? "")
        ? false
        : 2_000,
    refetchIntervalInBackground: false,
  });
  const routeDecisions = useQuery({
    queryKey: ["chat-demo-route-decisions", ticketId],
    queryFn: listDigitalEmployeeRouteDecisions,
    enabled: technicalMode && Boolean(ticketId),
    refetchInterval: 5_000,
  });

  useEffect(() => {
    minConversationVersionRef.current = 0;
    if (!conversationId) return;
    const controller = new AbortController();
    watchCustomerConversation(
      conversationId,
      (updated) => {
        if (updated.version < minConversationVersionRef.current) return;
        queryClient.setQueryData(
          ["chat-demo-conversation", conversationId],
          updated,
        );
      },
      controller.signal,
    ).catch(() => undefined);
    return () => controller.abort();
  }, [conversationId, queryClient]);

  useEffect(() => {
    window.localStorage.setItem(
      chatStateStorageKey,
      JSON.stringify({ conversationId, ticketId }),
    );
    const url = new URL(window.location.href);
    if (conversationId) {
      url.searchParams.set("conversation", conversationId);
    } else {
      url.searchParams.delete("conversation");
    }
    window.history.replaceState({}, "", url);
  }, [chatStateStorageKey, conversationId, ticketId]);

  useEffect(() => {
    const currentTicketId = conversation.data?.current_ticket_id;
    if (
      conversation.data?.id === conversationId &&
      currentTicketId &&
      currentTicketId !== ticketId
    ) {
      setTicketId(currentTicketId);
    }
  }, [conversation.data, conversationId, ticketId]);

  useEffect(() => {
    if (
      !conversationId ||
      !(conversation.error instanceof ApiError) ||
      conversation.error.status !== 404
    ) {
      return;
    }
    setConversationId("");
    setTicketId("");
    setInput("");
    setPendingBuyerText("");
    setLiveReply(null);
    liveConversationRef.current = null;
    setEditingReview(false);
    setReviewDraftText("");
    setManualSuggestion(null);
    setManualSuggestionError("");
    setFollowLatest(true);
    window.localStorage.removeItem(chatStateStorageKey);
  }, [
    chatStateStorageKey,
    conversation.error,
    conversationId,
  ]);

  const ecommerceScenario = scenario === "ecommerce";
  const requestPartyLabel = ecommerceScenario ? "买家" : "员工";
  const selectedCategory = ecommerceScenario
    ? categories.data?.find((category) => category.code === "vacuum_cup") ??
      categories.data?.[0]
    : undefined;
  const selectedProduct = useMemo(
    () => (!ecommerceScenario
      ? undefined :
      products.data?.find(
        (product) => product.category === selectedCategory?.name,
      ) ?? products.data?.[0]),
    [ecommerceScenario, products.data, selectedCategory?.name],
  );
  const selectedEmployee = ecommerceScenario
    ? employees.data?.find(
        (employee) =>
          employee.employee_key === "demo_vacuum_cup_customer_service",
      ) ??
      employees.data?.find(
        (employee) =>
          employee.status === "ACTIVE" &&
          employee.name.includes("保温杯客服"),
      )
    : employees.data?.find(
        (employee) =>
          employee.status === "ACTIVE" &&
          (employee.template_code === "enterprise_service_desk" ||
            employee.scenario_type === "enterprise_service"),
      );
  const selectedServiceEntry = ecommerceScenario
    ? serviceEntries.data?.find(
        (entry) => entry.code === "ecommerce_customer_service",
      ) ?? serviceEntries.data?.[0]
    : serviceEntries.data?.find(
        (entry) => entry.code === "enterprise_service_desk",
      );
  const serviceEntryDisplayName =
    selectedServiceEntry?.name ??
    (ecommerceScenario ? "国内电商客服入口" : "企业服务台入口");
  const serviceEntryEmployeeCount =
    selectedServiceEntry?.employees.length ??
    (selectedEmployee ? 1 : 0);

  const send = useMutation({
    mutationFn: async (content: string) => {
      const normalized = content.trim();
      if (!normalized) throw new Error("请输入要咨询的问题");
      setPendingBuyerText(normalized);
      let activeConversationId = conversationId;
      if (!activeConversationId) {
        const created = await createCustomerConversation({
          employeeId: selectedServiceEntry
            ? undefined
            : selectedEmployee?.id,
          serviceEntryId: selectedServiceEntry?.id,
          category:
            ecommerceScenario && selectedCategory
              ? {
                  name: selectedCategory.name,
                  profileId: selectedCategory.id,
                }
              : undefined,
          scenario,
        });
        activeConversationId = created.id;
        setConversationId(created.id);
      }
      liveConversationRef.current = activeConversationId;
      setLiveReply({
        conversationId: activeConversationId,
        turnId: null,
        text: "",
        stage: "正在连接数字员工",
      });
      let streamError = "";
      try {
        await streamCustomerConversationMessage(
          activeConversationId,
          {
            content: normalized,
            productId: ecommerceScenario ? selectedProduct?.id : undefined,
            sku: ecommerceScenario ? selectedProduct?.sku : undefined,
          },
          (event) => {
            if (liveConversationRef.current !== activeConversationId) return;
            if (event.type === "start") {
              setPendingBuyerText("");
              setLiveReply((current) =>
                current && current.conversationId === activeConversationId
                  ? {
                      ...current,
                      turnId: event.turn_id,
                      stage: "正在识别问题",
                    }
                  : current,
              );
              queryClient.setQueryData(
                ["chat-demo-conversation", activeConversationId],
                event.conversation,
              );
              setTicketId(event.conversation.current_ticket_id ?? "");
              return;
            }
            if (event.type === "status") {
              setLiveReply((current) =>
                current && current.conversationId === activeConversationId
                  ? { ...current, stage: event.stage }
                  : current,
              );
              return;
            }
            if (event.type === "delta") {
              setLiveReply((current) =>
                current && current.conversationId === activeConversationId
                  ? { ...current, text: current.text + event.text }
                  : current,
              );
              return;
            }
            if (event.type === "replace") {
              setLiveReply((current) =>
                current && current.conversationId === activeConversationId
                  ? { ...current, text: event.text }
                  : current,
              );
              return;
            }
            if (event.type === "done") {
              minConversationVersionRef.current = Math.max(
                minConversationVersionRef.current,
                event.conversation.version,
              );
              queryClient.setQueryData(
                ["chat-demo-conversation", event.conversation.id],
                event.conversation,
              );
              setTicketId(event.conversation.current_ticket_id ?? "");
              return;
            }
            if (event.type === "error") {
              streamError =
                "数字员工这次没有完成回复，请稍后重试。";
            }
          },
        );
      } finally {
        if (liveConversationRef.current === activeConversationId) {
          liveConversationRef.current = null;
          setLiveReply(null);
        }
      }
      if (streamError) throw new Error(streamError);
    },
    onSuccess: async () => {
      setInput("");
      setPendingBuyerText("");
      setManualSuggestion(null);
      setManualSuggestionError("");
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-conversation"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-ticket"],
        }),
      ]);
    },
    onError: (error: Error, submittedText) => {
      setPendingBuyerText("");
      setInput((current) => current || submittedText);
      void queryClient.invalidateQueries({
        queryKey: ["chat-demo-conversation"],
      });
      message.error(error.message);
    },
  });

  const submit = (content = input) => {
    if (
      send.isPending ||
      employees.isLoading ||
      serviceEntries.isLoading ||
      !content.trim()
    ) {
      return;
    }
    const normalized = content.trim();
    setInput("");
    setFollowLatest(true);
    send.mutate(normalized);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const startNewConversation = () => {
    setConversationId("");
    setTicketId("");
    setInput("");
    setPendingBuyerText("");
    setLiveReply(null);
    liveConversationRef.current = null;
    setEditingReview(false);
    setReviewDraftText("");
    setManualSuggestion(null);
    setManualSuggestionError("");
    setFollowLatest(true);
    window.localStorage.removeItem(chatStateStorageKey);
  };

  const currentConversation: CustomerConversation | undefined =
    conversation.data;
  const currentTicket = ticket.data;
  const activeLiveReply =
    liveReply && liveReply.conversationId === conversationId
      ? liveReply
      : null;
  const messages = currentConversation?.messages ?? [];
  const currentTurn = currentConversation?.current_turn ?? null;
  const turnInFlight = Boolean(
    currentTurn &&
      ["RECEIVED", "RUNNING"].includes(currentTurn.status),
  );
  const currentTicketMessages = messages.filter(
    (item) =>
      !currentConversation?.current_ticket_id ||
      item.ticket_id === currentConversation.current_ticket_id,
  );
  const latestAssistant = [...currentTicketMessages]
    .reverse()
    .find((item) => item.role === "ASSISTANT");
  const currentTurnDeliveredAnswer = Boolean(
    currentTurn?.status === "COMPLETED" && latestAssistant,
  );

  useEffect(() => {
    if (!currentConversation) return;
    setLiveReply((current) =>
      current && current.conversationId !== currentConversation.id
        ? null
        : current,
    );
  }, [currentConversation]);

  const draftText = currentTicket?.draft?.text?.trim() ?? "";
  const draftAlreadyDelivered = Boolean(
    draftText &&
      latestAssistant &&
      latestAssistant.content.trim() === draftText,
  );
  const suggestionAlreadyDelivered = Boolean(
    manualSuggestion &&
      latestAssistant &&
      latestAssistant.content.trim() === manualSuggestion.text.trim(),
  );
  const reviewRejected = currentTicket?.draft?.status === "REJECTED";
  const processing = Boolean(
    ticketId &&
      currentTicket &&
      !terminalStates.has(currentTicket.workflow_state) &&
      !currentTicket.needs_human &&
      !draftText &&
      !latestAssistant,
  );
  const reviewDraft = useMutation({
    mutationFn: (input: {
      decision: "ACCEPTED" | "EDITED_AND_ACCEPTED" | "REJECTED";
      text?: string;
    }) => {
      if (!currentTicket?.draft) {
        throw new Error("当前没有可审核的回复草稿");
      }
      return reviewTicket(
        currentTicket.id,
        currentTicket.version,
        input.decision,
        input.text,
      );
    },
    onSuccess: (_result, input) => {
      setEditingReview(false);
      message.success(
        input.decision === "REJECTED"
          ? "回复已退回，并转入人工处理"
          : input.decision === "EDITED_AND_ACCEPTED"
            ? "修改后的回复已通过审核并发送"
            : "审核通过，数字员工回复已进入发送流程",
      );
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-ticket", ticketId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-route-decisions", ticketId],
        }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const requestManualSuggestion = useMutation({
    mutationFn: () => {
      if (!conversationId) throw new Error("当前还没有对话");
      return generateCustomerReplySuggestion(conversationId);
    },
    onSuccess: (result) => {
      setManualSuggestion(result);
      setManualSuggestionError("");
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["chat-demo-ticket", ticketId],
        }),
      ]);
      message.success(
        result.fallback_used
          ? "模型调用失败，已生成有知识依据的本地建议"
          : "AI 回复建议已生成",
      );
    },
    onError: (error: Error) => {
      setManualSuggestion(null);
      setManualSuggestionError(
        error instanceof ApiError &&
          error.code === "KNOWLEDGE_NOT_FOUND"
          ? "当前会话没有可支撑回复的企业知识。系统不会编造答案，请补充知识或进入工作台手工处理。"
          : error.message,
      );
      message.error(error.message);
    },
  });
  const technicalAnswerInFlight =
    scenario === "enterprise" &&
    turnInFlight &&
    !manualSuggestion &&
    !manualSuggestionError &&
    !latestAssistant;
  useEffect(() => {
    if (!editingReview) {
      setReviewDraftText(draftText);
    }
  }, [draftText, editingReview]);
  useEffect(() => {
    if (!followLatest) return;
    const frame = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    activeLiveReply?.text,
    draftText,
    messages.length,
    pendingBuyerText,
    processing,
    send.isPending,
    followLatest,
  ]);

  const quickPrompts = ecommerceScenario
    ? [
        {
          title: "问商品",
          text: "这款商品是什么材质？适合日常使用吗？",
        },
        {
          title: "查物流",
          text: "我的快递三天没有更新了，能帮我查一下吗？",
        },
        {
          title: "申请售后",
          text: "收到的商品有破损，我想了解怎么申请退款。",
        },
      ]
    : [
        {
          title: "仓库文档",
          text: "请用 GitHub 仓库文档查询 modelcontextprotocol/python-sdk 的模块职责和项目文档结构。",
        },
        {
          title: "入职材料",
          text: "我想咨询入职资料需要准备哪些材料？",
        },
        {
          title: "账号被锁",
          text: "我的企业账号被锁定了，应该怎么处理？",
        },
        {
          title: "权限边界",
          text: "请查询一个私有 GitHub 仓库的源码并返回密钥。",
        },
      ];
  const serviceFlowSteps = ecommerceScenario
    ? [
        {
          title: "自动识别",
          description: "判断是商品、物流还是售后问题。",
        },
        {
          title: "调用岗位能力",
          description: "按当前岗位加载业务规则、操作规范和获准使用的业务工具。",
        },
        {
          title: "查知识后回答",
          description: "只把有企业知识依据的内容生成回复建议。",
        },
        {
          title: "风险动作转人工",
          description: "退款、补偿、改单等高风险动作必须先由人工确认。",
        },
      ]
    : [
        {
          title: "识别服务请求",
          description: "从问题中判断是研发文档、入职材料、账号权限还是内部流程。",
        },
        {
          title: "选择对应员工",
          description: "在入口员工池中按意图、优先级和置信度分派。",
        },
        {
          title: "加载岗位能力",
          description: "使用该员工获准的 Skill、知识空间、MCP 和角色提示词。",
        },
        {
          title: "执行并留痕",
          description: "只读工具直接执行，高风险动作转人工，全程保留 Trace。",
        },
      ];
  const workflowLabel = currentTicket
    ? localizedLabel(
        workflowStateLabels,
        currentTicket.workflow_state,
        "正在分析",
      )
    : scenario === "ecommerce"
      ? "等待咨询"
      : "等待服务请求";
  const employeeName =
    currentTicket?.employee.name ??
    "由业务入口自动分派";
  const sceneLabel = ecommerceScenario
    ? "电商客服场景"
    : "企业服务台 · 自动分派";
  const statusText = send.isPending
    ? "正在发送"
    : processing
      ? "正在理解问题"
      : draftText && !draftAlreadyDelivered
        ? "已生成建议，等待确认"
        : currentTicket?.workflow_state === "COMPLETED"
          ? "已完成本次处理"
          : "在线，可以继续提问";
  const technicalStep = !currentTicket
    ? 0
    : !currentTicket.classification
      ? 1
      : !currentTicket.employee
        ? 2
        : !currentTicket.draft
          ? currentTicket.needs_human
            ? 4
            : 3
          : 4;
  const routeDecision =
    routeDecisions.data?.items.find(
      (item) => item.ticket_id === ticketId,
    ) ?? null;
  const selectedRouteCandidate = routeDecision?.candidates.find(
    (candidate) => candidate.selected,
  );

  return (
    <div className="chat-demo-page">
      <div className="chat-demo-heading">
        <div>
          <span className="eyebrow">
            {technicalMode
              ? "CUSTOMER SERVICE · TECHNICAL INSPECTOR"
              : ecommerceScenario
                ? "ECOMMERCE SERVICE DEMO"
                : "ENTERPRISE SERVICE DESK DEMO"}
          </span>
          <Title level={2}>
            {technicalMode
              ? "边对话，边看处理依据"
              : ecommerceScenario
                ? "像买家一样问，像客服一样答"
                : "像员工一样问，自动分派给对的人"}
          </Title>
          <Paragraph type="secondary">
            {technicalMode
              ? "保留真实对话，同时在右侧查看员工路由、分类置信度、知识引用、风险和处理状态。"
              : ecommerceScenario
                ? "不用先配置参数。直接输入问题，系统会自动识别意图、查知识并生成回复；遇到退款或高风险动作时会转人工确认。"
                : "研发文档、入职材料、账号权限和内部流程都可以直接问。系统会在同一个服务台入口里自动选择对应数字员工，并显示本次由谁处理。"}
          </Paragraph>
          <div className="chat-identity-strip">
            <div className="chat-identity-party operator">
              <span>当前视角</span>
              <strong>模拟{requestPartyLabel}</strong>
              <small>这里只体验请求方对话，不显示内部岗位身份</small>
            </div>
            <div className="chat-identity-connector" aria-hidden="true">
              →
            </div>
            <div className="chat-identity-party conversation">
              <span>这段对话里</span>
              <strong>
                你（模拟{requestPartyLabel}）↔{" "}
                {currentTicket?.employee ? (
                  <Button
                    type="link"
                    className="employee-profile-link"
                    onClick={() =>
                      setProfileEmployeeId(currentTicket.employee.id)
                    }
                  >
                    {currentTicket.employee.name}
                  </Button>
                ) : (
                  employeeName
                )}
              </strong>
              <small>
                {serviceEntryDisplayName} · {serviceEntryEmployeeCount} 名数字员工可参与分派
              </small>
            </div>
          </div>
        </div>
        <Space wrap>
          {!technicalMode && (
            <Button
              onClick={() =>
                onOpenWorkspace(conversationId || undefined)
              }
            >
              进入服务工作台
            </Button>
          )}
          <Button onClick={startNewConversation}>重新开始</Button>
        </Space>
      </div>

      <div
        className={`chat-demo-grid ${
          technicalMode ? "technical" : ""
        }`}
      >
        <Card className="chat-window" styles={{ body: { padding: 0 } }}>
          <div className="chat-window-header">
            <Space size="middle">
              <div className="chat-avatar">AI</div>
              <div>
                <Space size={8}>
                  {currentTicket?.employee ? (
                    <Button
                      type="link"
                      className="employee-profile-link"
                      onClick={() =>
                        setProfileEmployeeId(currentTicket.employee!.id)
                      }
                    >
                      {currentTicket.employee.name}
                    </Button>
                  ) : (
                    <Text strong>{employeeName}</Text>
                  )}
                  <span className="chat-online">
                    <span className="chat-online-dot" />
                    在线
                  </span>
                </Space>
                <div className="chat-window-subtitle">
                  {currentTicket?.employee
                    ? `本次由该员工处理 · ${statusText}`
                    : `${sceneLabel} · ${statusText}`}
                </div>
              </div>
            </Space>
            <Space wrap size={4}>
              <Tag color={currentTicket ? "blue" : "default"}>
                {workflowLabel}
              </Tag>
              {currentTicket?.risk?.level && (
                <Tag color={riskColor(currentTicket.risk.level)}>
                  {currentTicket.risk.level}
                </Tag>
              )}
            </Space>
          </div>

          <div
            ref={scrollRef}
            className="chat-scroll"
            role="log"
            aria-live="polite"
            onScroll={(event) => {
              const container = event.currentTarget;
              const distanceToBottom =
                container.scrollHeight -
                container.scrollTop -
                container.clientHeight;
              setFollowLatest(distanceToBottom < 64);
            }}
          >
            <div className="chat-message-row assistant">
              <Avatar className="chat-small-avatar">AI</Avatar>
              <div className="chat-message-content">
                <div className="chat-bubble">
                  {ecommerceScenario
                    ? "您好，我是电商客服数字员工。您可以直接描述商品、物流或售后问题，我会先给出处理建议；涉及退款等高风险动作时，会转人工确认。"
                    : "您好，这里是企业服务台。研发仓库、入职材料、账号权限和内部流程都可以直接问，我会根据问题分派给对应的数字员工。分派结果和员工的 Skill、知识、MCP 配置都可以在对话里点开查看；高风险事项会转人工确认。"}
                </div>
                <div className="chat-bubble-meta">数字员工 · 刚刚</div>
              </div>
            </div>

            {conversation.isLoading && (
              <div className="chat-loading-messages" aria-label="正在加载会话">
                <Skeleton active avatar paragraph={{ rows: 2 }} />
                <Skeleton active avatar paragraph={{ rows: 3 }} />
              </div>
            )}

            {!conversation.isLoading && messages.map((item) => {
              const fromHuman =
                item.role === "ASSISTANT" &&
                item.created_by !== "digital_employee";
              const buyer = item.role === "BUYER";
              return (
                <div
                  className={`chat-message-row ${
                    buyer ? "buyer" : "assistant"
                  }`}
                  key={item.id}
                >
                  {!buyer && (
                    <Avatar className="chat-small-avatar">
                      {fromHuman ? "人" : "AI"}
                    </Avatar>
                  )}
                  <div className="chat-message-content">
                    <div
                      className={`chat-bubble ${
                        fromHuman ? "human" : ""
                      }`}
                    >
                      {item.content}
                    </div>
                    <div className="chat-bubble-meta">
                      {buyer
                        ? `你（${requestPartyLabel}）`
                        : fromHuman
                          ? `人工客服 · ${item.created_by}`
                          : currentTicket?.employee
                            ? `${currentTicket.employee.name} · 数字员工`
                            : "数字员工"}
                      {" · "}
                      {new Date(item.created_at).toLocaleTimeString(
                        "zh-CN",
                        {
                          hour: "2-digit",
                          minute: "2-digit",
                        },
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {pendingBuyerText && (
              <div className="chat-message-row buyer">
                <div className="chat-message-content">
                  <div className="chat-bubble chat-pending-buyer">
                    {pendingBuyerText}
                  </div>
                  <div className="chat-bubble-meta">
                    你（{requestPartyLabel}）· 发送中
                  </div>
                </div>
              </div>
            )}

            {activeLiveReply?.text && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-bubble-streaming">
                    {activeLiveReply.text}
                    <span className="chat-stream-caret" />
                  </div>
                  <div className="chat-bubble-meta">
                    {currentTicket?.employee
                      ? `${currentTicket.employee.name} · 数字员工`
                      : "数字员工"}
                    {" · "}
                    {activeLiveReply.stage || "正在回复"}
                  </div>
                </div>
              </div>
            )}

            {(send.isPending || processing || technicalAnswerInFlight) &&
              !activeLiveReply?.text && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-typing">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="chat-bubble-meta">
                    {activeLiveReply?.stage ??
                      (send.isPending
                        ? "消息已送达，正在创建服务任务"
                        : technicalAnswerInFlight
                          ? currentTurn?.stage_label ?? "正在处理本轮问题"
                          : !currentTicket
                            ? "正在读取业务上下文"
                            : !currentTicket.classification
                              ? "正在识别问题类型"
                              : "正在检索知识并生成处理建议")}
                  </div>
                </div>
              </div>
            )}

            {draftText &&
              !draftAlreadyDelivered &&
              scenario !== "enterprise" && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-suggestion">
                    <div className="chat-suggestion-title">
                      {reviewRejected
                        ? "建议回复 · 已退回转人工"
                        : "建议回复 · 等待人工审核"}
                    </div>
                    {editingReview ? (
                      <TextArea
                        autoSize={{ minRows: 4, maxRows: 10 }}
                        value={reviewDraftText}
                        onChange={(event) =>
                          setReviewDraftText(event.target.value)
                        }
                      />
                    ) : (
                      draftText
                    )}
                    {currentTicket?.draft?.citations.length ? (
                      <div className="chat-citations">
                        <Text type="secondary">知识依据：</Text>
                        {currentTicket.draft.citations.map((citation) => (
                          <Tag key={`${citation.document_id}-${citation.title}`}>
                            {citation.title}
                          </Tag>
                        ))}
                      </div>
                    ) : null}
                    {currentTicket?.workflow_state ===
                      "PENDING_REVIEW" && (
                      <div className="chat-review-actions">
                        {editingReview ? (
                          <>
                            <Button
                              type="primary"
                              size="small"
                              loading={reviewDraft.isPending}
                              disabled={!reviewDraftText.trim()}
                              onClick={() =>
                                reviewDraft.mutate({
                                  decision: "EDITED_AND_ACCEPTED",
                                  text: reviewDraftText.trim(),
                                })
                              }
                            >
                              修改后发送
                            </Button>
                            <Button
                              size="small"
                              disabled={reviewDraft.isPending}
                              onClick={() => {
                                setEditingReview(false);
                                setReviewDraftText(draftText);
                              }}
                            >
                              取消修改
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              type="primary"
                              size="small"
                              loading={reviewDraft.isPending}
                              onClick={() =>
                                reviewDraft.mutate({
                                  decision: "ACCEPTED",
                                })
                              }
                            >
                              通过并发送
                            </Button>
                            <Button
                              size="small"
                              disabled={reviewDraft.isPending}
                              onClick={() => {
                                setEditingReview(true);
                                setReviewDraftText(draftText);
                              }}
                            >
                              修改后发送
                            </Button>
                            <Button
                              danger
                              size="small"
                              loading={reviewDraft.isPending}
                              onClick={() =>
                                reviewDraft.mutate({
                                  decision: "REJECTED",
                                })
                              }
                            >
                              退回转人工
                            </Button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="chat-bubble-meta">
                    {reviewRejected
                      ? "数字员工建议 · 已退回，后续在人工处理流程中跟进"
                      : `数字员工建议 · 审核操作就在这条气泡内完成${
                          currentTicket?.needs_human
                            ? " · 需要人工确认"
                            : ""
                        }`}
                  </div>
                </div>
              </div>
            )}

            {currentTicket?.needs_human &&
              !draftText &&
              !manualSuggestion &&
              !currentTurnDeliveredAnswer &&
              !turnInFlight &&
              !send.isPending &&
              !requestManualSuggestion.isPending && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-human-notice">
                    {ecommerceScenario
                      ? "这个问题涉及人工判断。数字员工已经完成识别，但不会替你做出退款、补偿或其他高风险决定，请进入服务工作台继续处理。"
                      : "这个问题需要进一步核实或跨部门处理。数字员工不会代替责任人做最终决定，请进入服务工作台继续处理。"}
                    <div className="chat-review-actions">
                      <Button
                        size="small"
                        loading={requestManualSuggestion.isPending}
                        disabled={!conversationId}
                        onClick={() => requestManualSuggestion.mutate()}
                      >
                        {requestManualSuggestion.isPending
                          ? "正在生成 AI 建议"
                          : "生成 AI 回复建议"}
                      </Button>
                      <Button
                        size="small"
                        onClick={() =>
                          onOpenWorkspace(conversationId || undefined)
                        }
                      >
                        进入工作台处理
                      </Button>
                    </div>
                  </div>
                  <div className="chat-bubble-meta">
                    数字员工 · 已请求人工介入
                  </div>
                </div>
              </div>
            )}

            {manualSuggestionError &&
              (scenario === "enterprise" || !draftText) &&
              !requestManualSuggestion.isPending && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-human-notice">
                    <div className="chat-suggestion-title">
                      AI 建议暂不可用
                    </div>
                    {manualSuggestionError}
                    <div className="chat-review-actions">
                      <Button
                        size="small"
                        loading={requestManualSuggestion.isPending}
                        onClick={() => requestManualSuggestion.mutate()}
                      >
                        重新生成
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {manualSuggestion && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">AI</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble chat-suggestion">
                    <div className="chat-suggestion-title">
                      {suggestionAlreadyDelivered
                        ? "本次 Agent 执行详情"
                        : scenario === "enterprise"
                          ? "数字员工实时回答 · 已完成知识检索和工具规划"
                          : "AI 补充建议 · 仅供人工参考"}
                    </div>
                    {!suggestionAlreadyDelivered && manualSuggestion.text}
                    {manualSuggestion.citations.length > 0 && (
                      <div className="chat-citations">
                        <Text type="secondary">知识依据：</Text>
                        {manualSuggestion.citations.map((citation) => (
                          <Tag
                            key={`${citation.document_id}-${citation.version}`}
                          >
                            {citation.title}
                          </Tag>
                        ))}
                      </div>
                    )}
                    {manualSuggestion.trace.length > 0 && (
                      <div className="chat-citations">
                        <Text type="secondary">执行链路：</Text>
                        {manualSuggestion.trace.map((step) => (
                          <Tag key={step}>{step}</Tag>
                        ))}
                      </div>
                    )}
                    {manualSuggestion.tool_calls.length > 0 && (
                      <div className="chat-citations">
                        <Text type="secondary">工具调用：</Text>
                        {manualSuggestion.tool_calls.map((toolCall) => (
                          <Tag
                            key={toolCall.tool_call_id}
                            color={
                              toolCall.status === "SUCCEEDED"
                                ? "green"
                                : "red"
                            }
                          >
                            {toolCall.tool_id} · {toolCall.status} ·{" "}
                            {toolCall.duration_ms}ms
                          </Tag>
                        ))}
                      </div>
                    )}
                    <div className="chat-review-actions">
                      <Button
                        size="small"
                        onClick={() =>
                          onOpenWorkspace(conversationId || undefined)
                        }
                      >
                        {scenario === "enterprise"
                          ? "查看完整 Trace 与工作台"
                          : "带入工作台人工处理"}
                      </Button>
                    </div>
                  </div>
                  <div className="chat-bubble-meta">
                    {manualSuggestion.provider} /{" "}
                    {manualSuggestion.model} · 未发送
                  </div>
                </div>
              </div>
            )}

            {!conversationId && !messages.length && !pendingBuyerText && (
              <div className="chat-quick-prompts">
                <Text type="secondary">可以试试这样问：</Text>
                <Space wrap>
                  {quickPrompts.map((prompt) => (
                    <Button
                      key={prompt.title}
                      className="chat-prompt-button"
                      onClick={() => submit(prompt.text)}
                      disabled={
                        send.isPending ||
                        employees.isLoading ||
                        serviceEntries.isLoading
                      }
                    >
                      {prompt.title}
                    </Button>
                  ))}
                </Space>
              </div>
            )}
          </div>
          {!followLatest && (
            <Button
              className="chat-jump-latest"
              size="small"
              onClick={() => setFollowLatest(true)}
            >
              查看最新消息
            </Button>
          )}

          <div className="chat-composer">
            <TextArea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              autoSize={{ minRows: 1, maxRows: 4 }}
              maxLength={2_000}
              placeholder={`输入${requestPartyLabel}问题，按 Enter 发送，Shift + Enter 换行`}
              disabled={send.isPending}
            />
            <Button
              type="primary"
              className="chat-send-button"
              loading={send.isPending}
              disabled={
                !input.trim() ||
                employees.isLoading ||
                serviceEntries.isLoading
              }
              onClick={() => submit()}
            >
              发送
            </Button>
          </div>
          <div className="chat-composer-note">
            沙盒演示：消息只写入本地演示会话，不会发送到任何外部业务系统。
          </div>
        </Card>

        <div
          className={`chat-side-panel ${
            technicalMode ? "technical" : ""
          }`}
        >
          {technicalMode ? (
            <>
              <Card
                className="technical-inspector"
                size="small"
                title="技术面板 · 聊天内容不会跳走"
                extra={<Tag color="cyan">TECH</Tag>}
              >
                <Alert
                  type="info"
                  showIcon
                  message="这里只解释当前这条消息"
                  description="四个标签分别回答：走到哪一步、为什么选这个员工、回答有没有依据、需不需要人工审核。切换标签不会离开当前对话。"
                  style={{ marginBottom: 12 }}
                />
                <Tabs
                  size="small"
                  items={[
                    {
                      key: "process",
                      label: "① 走到哪",
                      children: (
                        <Space
                          direction="vertical"
                          size="middle"
                          style={{ width: "100%" }}
                        >
                          <Steps
                            direction="vertical"
                            size="small"
                            current={technicalStep}
                            items={[
                              {
                                title: "收到业务消息",
                                description: "消息已写入当前演示会话。",
                              },
                              {
                                title: "识别业务类型",
                                description:
                                  currentTicket?.classification
                                    ? `识别为 ${
                                        categoryLabels[
                                          currentTicket.classification.primary
                                        ] ??
                                        currentTicket.classification.primary
                                      }，把握 ${(
                                        currentTicket.classification
                                          .confidence * 100
                                      ).toFixed(0)}%。`
                                    : "等待分类结果。",
                              },
                              {
                                title: "选择数字员工",
                                description:
                                  currentTicket?.employee.name ??
                                  "等待选择处理员工。",
                              },
                              {
                                title: "查资料并写回复",
                                description: currentTicket?.draft
                                  ? `已引用 ${
                                      currentTicket.draft.citations.length
                                    } 份资料。`
                                  : "正在检索知识或等待人工补充资料。",
                              },
                              {
                                title: "自动发送或人工审核",
                                description:
                                  currentTicket?.workflow_state ===
                                  "COMPLETED"
                                    ? "本次处理已完成。"
                                    : currentTicket?.needs_human
                                      ? "当前需要人工确认。"
                                      : "根据风险和依据状态决定。",
                              },
                            ]}
                          />
                          <Descriptions
                            size="small"
                            column={1}
                            items={[
                              {
                                key: "state",
                                label: "当前处理状态",
                                children:
                                  currentTicket?.workflow_state ?? "等待发送",
                              },
                              {
                                key: "risk",
                                label: "为什么要谨慎",
                                children: currentTicket?.risk
                                  ? `${currentTicket.risk.level} · ${currentTicket.risk.reason_codes.join("、")}`
                                  : "尚未识别风险",
                              },
                              {
                                key: "human",
                                label: "为什么找人工",
                                children:
                                  currentTicket?.routing.human_reason ??
                                  "当前不需要额外人工介入",
                              },
                            ]}
                          />
                        </Space>
                      ),
                    },
                    {
                      key: "routing",
                      label: "② 为什么选它",
                      children: routeDecision ? (
                        <Space
                          direction="vertical"
                          size="small"
                          style={{ width: "100%" }}
                        >
                          <Alert
                            type="success"
                            showIcon
                            message={`最终交给：${
                              selectedRouteCandidate?.employee_name ??
                              currentTicket?.employee.name ??
                              "-"
                            }`}
                            description={routeDecision.reason}
                          />
                          {(currentTicket?.employee?.id ??
                            selectedRouteCandidate?.employee_id) && (
                            <Button
                              size="small"
                              onClick={() =>
                                setProfileEmployeeId(
                                  currentTicket?.employee?.id ??
                                    selectedRouteCandidate!.employee_id,
                                )
                              }
                            >
                              查看员工 Skill、知识与 MCP
                            </Button>
                          )}
                          <Space wrap size={4}>
                            <Tag>
                              判断把握{" "}
                              {(routeDecision.confidence * 100).toFixed(0)}%
                            </Tag>
                            {selectedRouteCandidate && (
                              <>
                                <Tag>
                                  关键词{" "}
                                  {(
                                    (selectedRouteCandidate.keyword_score ??
                                      0) * 100
                                  ).toFixed(0)}
                                </Tag>
                                <Tag>
                                  语义{" "}
                                  {(
                                    (selectedRouteCandidate.semantic_score ??
                                      0) * 100
                                  ).toFixed(0)}
                                </Tag>
                              </>
                            )}
                          </Space>
                          <Collapse
                            size="small"
                            items={[
                              {
                                key: "candidates",
                                label: `查看全部 ${routeDecision.candidates.length} 个候选员工`,
                                children: (
                                  <Space
                                    direction="vertical"
                                    size={6}
                                    style={{ width: "100%" }}
                                  >
                                    {routeDecision.candidates.map(
                                      (candidate) => (
                                        <div
                                          className="technical-candidate-row"
                                          key={candidate.employee_id}
                                        >
                                          <Space wrap size={4}>
                                            <Text strong>
                                              {candidate.employee_name}
                                            </Text>
                                            {candidate.selected && (
                                              <Tag color="green">
                                                最终选择
                                              </Tag>
                                            )}
                                            {!candidate.eligible && (
                                              <Tag color="red">
                                                不参与派单
                                              </Tag>
                                            )}
                                          </Space>
                                          {(candidate.matched_intents ?? [])
                                            .length > 0 && (
                                            <Text type="secondary">
                                              命中：
                                              {(
                                                candidate.matched_intents ?? []
                                              ).join("、")}
                                            </Text>
                                          )}
                                          {(candidate.excluded_reasons ?? [])
                                            .length > 0 && (
                                            <Text type="danger">
                                              原因：
                                              {(
                                                candidate.excluded_reasons ??
                                                []
                                              ).join("；")}
                                            </Text>
                                          )}
                                        </div>
                                      ),
                                    )}
                                  </Space>
                                ),
                              },
                            ]}
                          />
                        </Space>
                      ) : (
                        <Alert
                          type={currentTicket ? "info" : "success"}
                          showIcon
                          message={
                            currentTicket
                              ? "本次使用预置演示员工"
                              : "还没有发起会话"
                          }
                          description={
                            currentTicket
                            ? "当前商品咨询由业务入口员工池中的商品客服处理。可在“业务入口与员工路由”页面查看员工池和最近派单结果。"
                              : "发送第一条消息后，这里会展示自动路由结果；当前聊天使用预置演示员工。"
                          }
                        />
                      ),
                    },
                    {
                      key: "evidence",
                      label: "③ 回答依据",
                      children: (
                        <Space
                          direction="vertical"
                          size={10}
                          style={{ width: "100%" }}
                        >
                          <Alert
                            type={
                              currentTicket?.draft?.grounding_status ===
                              "GROUNDED"
                                ? "success"
                                : "warning"
                            }
                            showIcon
                            message="回答依据怎么理解"
                            description="数字员工不能只凭感觉回答。这里显示它查了哪些资料、用了哪个模型，以及每句话是否有资料支持。"
                          />
                          <Descriptions
                            size="small"
                            column={1}
                            items={[
                              {
                                key: "model",
                                label: "回复由谁生成",
                                children: currentTicket?.draft
                                  ? `${currentTicket.draft.generator_provider ?? "未知服务"} / ${
                                      currentTicket.draft.generator_model ??
                                      "未知模型"
                                    }`
                                  : "尚未生成回复",
                              },
                              {
                                key: "grounding",
                                label: "是否有资料支持",
                                children: currentTicket?.draft
                                  ? localizedLabel(
                                      groundingStatusLabels,
                                      currentTicket.draft.grounding_status,
                                    )
                                  : "等待生成",
                              },
                              {
                                key: "citations",
                                label: "引用了多少资料",
                                children: `${
                                  currentTicket?.draft?.citations.length ?? 0
                                } 份`,
                              },
                              {
                                key: "claims",
                                label: "核对了多少回答要点",
                                children: `${
                                  currentTicket?.draft?.claims.length ?? 0
                                } 条`,
                              },
                            ]}
                          />
                          <Space wrap size={4}>
                            {currentTicket?.draft?.citations.map(
                              (citation) => (
                                <Tag
                                  key={`${citation.document_id}-${citation.version}`}
                                >
                                  {citation.title} · v{citation.version}
                                </Tag>
                              ),
                            )}
                          </Space>
                          {(currentTicket?.draft?.claims.length ?? 0) > 0 && (
                            <Collapse
                              size="small"
                              items={[
                                {
                                  key: "claims",
                                  label: "查看逐条依据核对",
                                  children: (
                                    <Space
                                      direction="vertical"
                                      size={6}
                                      style={{ width: "100%" }}
                                    >
                                      {currentTicket?.draft?.claims.map(
                                        (claim, index) => (
                                          <div
                                            className="technical-candidate-row"
                                            key={`${claim.text}-${index}`}
                                          >
                                            <Text>{claim.text}</Text>
                                            <Text type="secondary">
                                              {claim.verification_verdict ??
                                                "待核对"}
                                              {claim.verification_reason
                                                ? ` · ${claim.verification_reason}`
                                                : ""}
                                            </Text>
                                          </div>
                                        ),
                                      )}
                                    </Space>
                                  ),
                                },
                              ]}
                            />
                          )}
                        </Space>
                      ),
                    },
                    {
                      key: "review",
                      label: "④ 人工审核",
                      children: (
                        <Space
                          direction="vertical"
                          size={10}
                          style={{ width: "100%" }}
                        >
                          <Alert
                            type="info"
                            showIcon
                            message="审核不是审核代码"
                            description="审核是确认数字员工写好的回复能不能发给用户，以及是否允许执行退款、补偿或其他高风险业务动作。"
                          />
                          {currentTicket?.draft ? (
                            <>
                              <Descriptions
                                size="small"
                                column={1}
                                items={[
                                  {
                                    key: "draft-status",
                                    label: "草稿状态",
                                    children: localizedLabel(
                                      draftStateLabels,
                                      currentTicket.draft.status,
                                    ),
                                  },
                                  {
                                    key: "draft-preview",
                                    label: "准备发送的内容",
                                    children: (
                                      <Paragraph
                                        ellipsis={{
                                          rows: 5,
                                          expandable: true,
                                        }}
                                        style={{ marginBottom: 0 }}
                                      >
                                        {currentTicket.draft.text}
                                      </Paragraph>
                                    ),
                                  },
                                ]}
                              />
                              {currentTicket.needs_human &&
                                currentTicket.workflow_state !==
                                  "COMPLETED" && (
                                  <Alert
                                    type="warning"
                                    showIcon
                                    message="草稿已生成，但业务规则要求人工确认"
                                    description={
                                      currentTicket.routing.human_reason ??
                                      "请在完整工作台核对身份、订单或审批条件。"
                                    }
                                  />
                                )}
                              {currentTicket.workflow_state ===
                                "PENDING_REVIEW" && (
                                <Alert
                                  type="info"
                                  showIcon
                                  message="审核操作在左侧对话气泡中完成"
                                  description="可以直接通过、修改后发送，或退回转人工；这里只解释审核依据，不需要再打开另一个页面。"
                                />
                              )}
                              {currentTicket.workflow_state ===
                                "COMPLETED" && (
                                <Alert
                                  type="success"
                                  showIcon
                                  message="本次回复已经通过审核并完成发送"
                                />
                              )}
                            </>
                          ) : (
                            <Alert
                              type={
                                currentTicket?.needs_human
                                  ? "warning"
                                  : "info"
                              }
                              showIcon
                              message={
                                currentTicket?.needs_human
                                  ? "需要人工补充资料或接管"
                                  : "还没有可审核的回复"
                              }
                              description={
                                currentTicket?.needs_human
                                  ? `原因：${
                                      currentTicket.routing.human_reason ??
                                      "业务规则要求人工处理"
                                    }`
                                  : "等数字员工完成知识检索和回复生成后，再回到这里审核。"
                              }
                            />
                          )}
                          <Button
                            onClick={() =>
                              onOpenWorkspace(
                                conversationId || undefined,
                              )
                            }
                          >
                            需要更多审核工具时打开完整工作台
                          </Button>
                          {onOpenAdmin && (
                            <Button type="link" onClick={onOpenAdmin}>
                              打开管理员视图
                            </Button>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            </>
          ) : (
            <>
              <Card size="small" title="这条消息会怎么处理">
                <ol className="chat-flow-list">
                  {serviceFlowSteps.map((step) => (
                    <li key={step.title}>
                      <strong>{step.title}</strong>
                      <span>{step.description}</span>
                    </li>
                  ))}
                </ol>
              </Card>

              <Card size="small" title="当前上下文">
                <Space
                  direction="vertical"
                  size={8}
                  style={{ width: "100%" }}
                >
                  <div className="chat-context-row">
                    <Text type="secondary">当前视角</Text>
                    <Text>模拟{requestPartyLabel}</Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">对话双方</Text>
                    <Text>
                      你（模拟{requestPartyLabel}）↔ {employeeName}
                    </Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">业务入口</Text>
                    <Text>{serviceEntryDisplayName}</Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">
                      {ecommerceScenario ? "商品" : "业务对象"}
                    </Text>
                    <Text>
                      {ecommerceScenario
                        ? selectedProduct?.name ?? "自动识别"
                        : "内部服务请求"}
                    </Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">数字员工</Text>
                    <Text>
                      {currentTicket?.employee ? (
                        <Button
                          type="link"
                          className="employee-profile-link"
                          onClick={() =>
                            setProfileEmployeeId(
                              currentTicket.employee.id,
                            )
                          }
                        >
                          {currentTicket.employee.name}
                        </Button>
                      ) : (
                        "等待自动分派"
                      )}
                    </Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">业务类型</Text>
                    <Text>
                      {currentTicket?.classification?.primary
                        ? categoryLabels[
                            currentTicket.classification.primary
                          ] ?? currentTicket.classification.primary
                        : "等待识别"}
                    </Text>
                  </div>
                  <div className="chat-context-row">
                    <Text type="secondary">会话状态</Text>
                    <Text>{statusText}</Text>
                  </div>
                </Space>
              </Card>
            </>
          )}

          {currentTicket?.needs_human && (
            <Alert
              type="warning"
              showIcon
              message="这次需要人工确认"
              description="数字员工已完成识别和建议，但退款、赔偿或高风险问题不能直接替人决定。"
              action={
                <Button
                  size="small"
                  onClick={() =>
                    onOpenWorkspace(conversationId || undefined)
                  }
                >
                  去处理
                </Button>
              }
            />
          )}

          {conversation.error ||
          ticket.error ||
          (technicalMode && routeDecisions.error) ? (
            <Alert
              type="error"
              showIcon
              message="会话读取失败"
              description="可以点击“重新开始”打开一个新的聊天演示。"
            />
          ) : null}
        </div>
      </div>
      <EmployeeProfileDrawer
        employeeId={profileEmployeeId}
        employee={
          employees.data?.find(
            (employee) => employee.id === profileEmployeeId,
          ) ?? null
        }
        open={Boolean(profileEmployeeId)}
        onClose={() => setProfileEmployeeId("")}
      />
    </div>
  );
}

export default function CustomerServicePage({
  technicalMode = false,
  section = "chat",
  onNavigate,
}: {
  technicalMode?: boolean;
  section?: CustomerServiceSection;
  onNavigate?: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [stored] = useState(loadSandboxState);
  const canOpenAdmin = ![
    "service-agent",
    "knowledge-operator",
    "business-manager",
  ].includes(getActiveTestIdentity().id);
  const [demoScenario, setDemoScenario] = useState<CustomerDemoScenario>(() =>
    new URLSearchParams(window.location.search).get("scenario") === "ecommerce"
      ? "ecommerce"
      : "enterprise",
  );
  const [employeeId, setEmployeeId] = useState(stored?.employeeId ?? "");
  const [currentAgentId, setCurrentAgentId] = useState("");
  const [conversationFilter, setConversationFilter] =
    useState<ConversationFilter>("mine");
  const [categoryProfileId, setCategoryProfileId] = useState(
    stored?.categoryProfileId ?? "",
  );
  const [productId, setProductId] = useState(stored?.productId ?? "");
  const [subject, setSubject] = useState(
    stored?.subject === "企业团队消息通知配置咨询"
      ? "公开 GitHub 仓库文档查询"
      : stored?.subject ?? "公开 GitHub 仓库文档查询",
  );
  const [body, setBody] = useState(
    stored?.body === "请问企业团队消息通知应该如何配置？"
      ? "请用 GitHub 仓库文档查询 modelcontextprotocol/python-sdk 的模块职责和项目文档结构。"
      : stored?.body ??
        "请用 GitHub 仓库文档查询 modelcontextprotocol/python-sdk 的模块职责和项目文档结构。",
  );
  const [ticketId, setTicketId] = useState(stored?.ticketId ?? "");
  const [editedText, setEditedText] = useState(stored?.editedText ?? "");
  const [manualReplyText, setManualReplyText] = useState("");
  const [autoSuggestionError, setAutoSuggestionError] = useState("");
  const lastAutoSuggestionKeyRef = useRef("");
  const [optimizationStyle, setOptimizationStyle] = useState<
    "professional" | "concise" | "empathetic"
  >("professional");
  const [historyScope, setHistoryScope] = useState<HistoryScope>("current");
  const [followLatest, setFollowLatest] = useState(true);
  const historyContainerRef = useRef<HTMLDivElement>(null);
  const conversationListRef = useRef<HTMLDivElement>(null);
  const ticketPanelRef = useRef<HTMLDivElement>(null);
  const [scrollToTicketOnLoad, setScrollToTicketOnLoad] = useState(false);
  const [logisticsOrderId, setLogisticsOrderId] = useState("");
  const [trackingNumber, setTrackingNumber] = useState("");
  const [carrierCode, setCarrierCode] = useState("");
  const [history, setHistory] = useState<ConversationTurn[]>(
    stored?.history ?? [],
  );
  const [conversationId, setConversationId] = useState(
    stored?.conversationId ?? "",
  );
  const [approvalFilter, setApprovalFilter] = useState("PENDING");
  const [approvalDecision, setApprovalDecision] = useState<{
    approval: McpToolApproval;
    decision: "APPROVE" | "REJECT";
  } | null>(null);
  const [approvalNote, setApprovalNote] = useState("");
  const [incidentFilter, setIncidentFilter] = useState("OPEN");
  const [incidentDecision, setIncidentDecision] = useState<{
    incident: McpActionIncident;
    action: "acknowledge" | "resolve";
  } | null>(null);
  const [incidentNote, setIncidentNote] = useState("");
  const [incidentOutcome, setIncidentOutcome] = useState<
    | "EXECUTED_AS_INTENDED"
    | "NOT_EXECUTED"
    | "EXECUTED_INCORRECTLY"
    | "INCONCLUSIVE"
  >("INCONCLUSIVE");
  const [compensationIncident, setCompensationIncident] =
    useState<McpActionIncident | null>(null);
  const [compensationToolId, setCompensationToolId] = useState("");
  const [compensationArguments, setCompensationArguments] = useState("{}");
  const [compensationNote, setCompensationNote] = useState("");
  const [assignmentResult, setAssignmentResult] =
    useState<AssignmentRunResult | null>(null);
  const [viewMode, setViewMode] = useState<CustomerServiceSurfaceMode>(() => {
    const requestedPane = new URLSearchParams(
      window.location.search,
    ).get("pane");
    if (requestedPane === "workbench") return "workspace";
    if (requestedPane === "admin" && technicalMode) return "admin";
    if (section === "workbench") return "workspace";
    if (
      section === "admin" ||
      section === "approvals" ||
      section === "incidents"
    ) {
      return "admin";
    }
    if (section === "chat") return "chat";
    const storedMode = window.localStorage.getItem(viewModeStorageKey);
    return storedMode === "admin" && technicalMode ? "admin" : "chat";
  });
  useEffect(() => {
    const onPopState = () => {
      setDemoScenario(
        new URLSearchParams(window.location.search).get("scenario") ===
          "ecommerce"
          ? "ecommerce"
          : "enterprise",
      );
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("pane")) return;
    url.searchParams.delete("pane");
    window.history.replaceState({}, document.title, url);
  }, []);

  useEffect(() => {
    if (!technicalMode && viewMode === "admin") {
      setViewMode("chat");
    }
  }, [technicalMode, viewMode]);

  useEffect(() => {
    window.localStorage.setItem(
      sandboxStorageKey,
      JSON.stringify({
        employeeId,
        subject,
        body,
        ticketId,
        editedText,
        history,
        conversationId,
        categoryProfileId,
        productId,
      } satisfies StoredSandboxState),
    );
  }, [
    body,
    categoryProfileId,
    conversationId,
    editedText,
    employeeId,
    history,
    productId,
    subject,
    ticketId,
  ]);

  useEffect(() => {
    window.localStorage.setItem(viewModeStorageKey, viewMode);
  }, [viewMode]);

  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
  });
  const categories = useQuery({
    queryKey: ["ecommerce-categories"],
    queryFn: listEcommerceCategoryProfiles,
  });
  const products = useQuery({
    queryKey: ["ecommerce-products"],
    queryFn: listEcommerceProducts,
  });
  const spaces = useQuery({
    queryKey: ["knowledge", "spaces"],
    queryFn: listKnowledgeSpaces,
  });
  const conversations = useQuery({
    queryKey: ["customer-conversations"],
    queryFn: listCustomerConversations,
    refetchInterval: 5_000,
  });
  const presence = useQuery({
    queryKey: ["customer-agent-presence"],
    queryFn: listCustomerAgentPresence,
    refetchInterval: 15_000,
  });
  const assignmentQueue = useQuery({
    queryKey: ["customer-assignment-queue"],
    queryFn: getCustomerAssignmentQueue,
    refetchInterval: 5_000,
  });
  const serviceAlerts = useQuery({
    queryKey: ["customer-service-alerts"],
    queryFn: listCustomerServiceAlerts,
    refetchInterval: 10_000,
  });
  const notifications = useQuery({
    queryKey: ["customer-service-notifications"],
    queryFn: listCustomerServiceNotifications,
    refetchInterval: 15_000,
  });
  const mcpApprovals = useQuery({
    queryKey: ["mcp-tool-approvals", approvalFilter],
    queryFn: () =>
      listMcpToolApprovals(
        approvalFilter === "ALL" ? undefined : approvalFilter,
      ),
    refetchInterval: 10_000,
  });
  const mcpIncidents = useQuery({
    queryKey: ["mcp-action-incidents", incidentFilter],
    queryFn: () =>
      listMcpActionIncidents(
        incidentFilter === "ALL" ? undefined : incidentFilter,
      ),
    refetchInterval: 10_000,
  });
  const metrics = useQuery({
    queryKey: ["customer-service-metrics"],
    queryFn: getCustomerServiceMetrics,
    refetchInterval: 10_000,
  });
  const historyMetrics = useQuery({
    queryKey: ["customer-service-history-metrics"],
    queryFn: () => getCustomerServiceHistoryMetrics(7),
    refetchInterval: 60_000,
  });
  const runtime = useQuery({
    queryKey: ["system-runtime"],
    queryFn: getRuntimeConfig,
  });
  const detail = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => getTicket(ticketId),
    enabled: Boolean(ticketId),
    refetchInterval: (query) =>
      terminalStates.has(query.state.data?.workflow_state ?? "")
        ? false
        : 2_000,
  });
  const conversationDetail = useQuery({
    queryKey: ["customer-conversation", conversationId],
    queryFn: () => getCustomerConversation(conversationId),
    enabled: Boolean(conversationId),
    refetchInterval: 10_000,
  });
  const knowledgeBindings = useQuery({
    queryKey: [
      "knowledge-bindings",
      detail.data?.employee.id ?? employeeId,
    ],
    queryFn: () =>
      listEmployeeKnowledgeBindings(detail.data?.employee.id ?? employeeId),
    enabled: Boolean(detail.data?.employee.id || employeeId),
  });

  const selectedCategory = categories.data?.find(
    (category) => category.id === categoryProfileId,
  );
  const categoryProducts = useMemo(
    () =>
      (products.data ?? []).filter(
        (product) => product.category === selectedCategory?.name,
      ),
    [products.data, selectedCategory?.name],
  );
  const feedbackSpace = useMemo(() => {
    const ticket = detail.data;
    if (!ticket) return null;
    const boundSpaceIds = new Set(
      (knowledgeBindings.data ?? [])
        .filter((binding) => binding.enabled)
        .map((binding) => binding.knowledge_space_id),
    );
    if (boundSpaceIds.size === 0) return null;
    const boundSpaces = (spaces.data ?? []).filter((space) =>
      boundSpaceIds.has(space.id),
    );
    const citedSpaceId = ticket.draft?.citations.find(
      (citation) => citation.space_id && boundSpaceIds.has(citation.space_id),
    )?.space_id;
    const citedSpace = boundSpaces.find((space) => space.id === citedSpaceId);
    if (citedSpace) return citedSpace;

    const categoryProfile = conversationDetail.data?.category_profile_id;
    const categoryName = conversationDetail.data?.category_name;
    const profileSpaces = categoryProfile
      ? boundSpaces.filter(
          (space) => space.category_profile_id === categoryProfile,
        )
      : [];
    const scopedSpaces =
      profileSpaces.length > 0
        ? profileSpaces
        : boundSpaces.filter(
            (space) => !categoryName || space.category === categoryName,
          );
    const preferredTokens =
      ticket.classification?.primary === "ecommerce_aftersales"
        ? ["售后", "aftersales", "after_sales"]
        : ["售前", "presales", "pre_sales"];
    return (
      scopedSpaces.find((space) => {
        const searchable = `${space.code} ${space.name}`.toLowerCase();
        return preferredTokens.some((token) => searchable.includes(token));
      }) ??
      scopedSpaces[0] ??
      null
    );
  }, [
    conversationDetail.data?.category_name,
    conversationDetail.data?.category_profile_id,
    detail.data,
    knowledgeBindings.data,
    spaces.data,
  ]);
  useEffect(() => {
    if (!conversationId) return;
    const controller = new AbortController();
    watchCustomerConversation(
      conversationId,
      (conversation) => {
        queryClient.setQueryData(
          ["customer-conversation", conversationId],
          conversation,
        );
      },
      controller.signal,
    ).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        console.warn("customer conversation stream disconnected", error);
      }
    });
    return () => controller.abort();
  }, [conversationId, queryClient]);

  useEffect(() => {
    const sendHeartbeat = () => {
      heartbeatCustomerAgent(conversationId || undefined)
        .then((presence) => setCurrentAgentId(presence.agent_id))
        .catch(() => undefined);
    };
    sendHeartbeat();
    const timer = window.setInterval(sendHeartbeat, 15_000);
    return () => window.clearInterval(timer);
  }, [conversationId]);

  useEffect(() => {
    if (
      employees.data?.length &&
      (!employeeId ||
        !employees.data.some((employee) => employee.id === employeeId))
    ) {
      const preferred = employees.data.find((employee) =>
        employee.employee_key.includes("customer_service"),
      );
      setEmployeeId(preferred?.id ?? employees.data[0].id);
    }
  }, [employeeId, employees.data]);

  useEffect(() => {
    const available = categories.data ?? [];
    if (available.length === 0) return;
    if (
      categoryProfileId &&
      available.some((category) => category.id === categoryProfileId)
    ) {
      return;
    }
    const preferred =
      available.find((category) => category.code === "vacuum_cup") ??
      available[0];
    setCategoryProfileId(preferred.id);
  }, [categories.data, categoryProfileId]);

  useEffect(() => {
    if (!selectedCategory) return;
    if (
      productId &&
      categoryProducts.some((product) => product.id === productId)
    ) {
      return;
    }
    setProductId(categoryProducts[0]?.id ?? "");
  }, [categoryProducts, productId, selectedCategory]);

  useEffect(() => {
    setEditedText(detail.data?.draft?.text ?? "");
  }, [detail.data?.draft?.text]);

  useEffect(() => {
    setManualReplyText("");
    setHistoryScope("current");
    setFollowLatest(true);
  }, [conversationId]);

  useEffect(() => {
    const currentTicketId = conversationDetail.data?.current_ticket_id;
    if (currentTicketId) setTicketId(currentTicketId);
    const conversationEmployeeId = conversationDetail.data?.employee_id;
    if (conversationEmployeeId) setEmployeeId(conversationEmployeeId);
    const conversationCategoryId =
      conversationDetail.data?.category_profile_id;
    if (conversationCategoryId) setCategoryProfileId(conversationCategoryId);
  }, [conversationDetail.data]);

  const createTicket = useMutation({
    mutationFn: async (input: {
      subject: string;
      body: string;
      newConversation?: boolean;
      autoRoute?: boolean;
    }) => {
      const conversation = conversationId && !input.newConversation
        ? { id: conversationId }
        : await createCustomerConversation({
            employeeId: input.autoRoute ? undefined : employeeId,
            category:
              demoScenario === "ecommerce" && categoryProfileId
                ? {
                    name:
                      categories.data?.find(
                        (item) => item.id === categoryProfileId,
                      )?.name ?? "通用商品",
                    profileId: categoryProfileId,
                  }
                : undefined,
            scenario: demoScenario,
          });
      const updated = await addCustomerConversationMessage(conversation.id, {
        content: `${input.subject}\n${input.body}`,
        productId:
          demoScenario === "ecommerce"
            ? categoryProducts.find((product) => product.id === productId)?.id
            : undefined,
        sku:
          demoScenario === "ecommerce"
            ? categoryProducts.find((product) => product.id === productId)?.sku
            : undefined,
      });
      return updated;
    },
    onSuccess: (conversation, input) => {
      setHistory((current) =>
        input.newConversation
          ? [{ role: "BUYER", text: input.body }]
          : [...current, { role: "BUYER", text: input.body }],
      );
      setConversationId(conversation.id);
      setTicketId(conversation.current_ticket_id ?? "");
      setScrollToTicketOnLoad(true);
      queryClient.invalidateQueries({ queryKey: ["customer-conversations"] });
      queryClient.invalidateQueries({ queryKey: ["customer-assignment-queue"] });
      message.success("测试问题已提交，接下来接管会话并查看处理结果");
    },
    onError: (error: Error) => message.error(error.message),
  });
  const review = useMutation({
    mutationFn: ({
      decision,
      text,
    }: {
      decision: "ACCEPTED" | "EDITED_AND_ACCEPTED";
      text?: string;
    }) => reviewTicket(detail.data!.id, detail.data!.version, decision, text),
    onSuccess: async (_result, variables) => {
      const answer =
        variables.decision === "EDITED_AND_ACCEPTED"
          ? variables.text
          : detail.data?.draft?.text;
      if (answer) {
        setHistory((current) => [
          ...current,
          { role: "ASSISTANT", text: answer },
        ]);
      }
      message.success("审核结果已保存");
      await queryClient.invalidateQueries({
        queryKey: ["ticket", ticketId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversation", conversationId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const feedback = useMutation({
    mutationFn: (rating: "POSITIVE" | "NEGATIVE") => {
      const ticket = detail.data;
      if (!ticket?.draft) throw new Error("还没有可评价的回答");
      if (!feedbackSpace) {
        throw new Error("当前数字员工没有可用于反馈的知识空间绑定");
      }
      return createKnowledgeFeedback({
        employeeId: ticket.employee.id,
        knowledgeSpaceId: feedbackSpace.id,
        ticketId: ticket.id,
        query: `${ticket.subject}\n${ticket.body}`,
        answer: ticket.draft.text,
        rating,
        reasonCode: rating === "POSITIVE" ? "HELPFUL" : "WRONG_ANSWER",
      });
    },
    onSuccess: (result) => {
      message.success(
        result.repair_task_id ? "反馈已记录并生成修复任务" : "反馈已记录",
      );
    },
    onError: (error: Error) => message.error(error.message),
  });
  const assignment = useMutation({
    mutationFn: async (action: "takeover" | "release") => {
      if (!conversationId || !conversationDetail.data) {
        throw new Error("当前没有可操作的会话");
      }
      return action === "takeover"
        ? takeOverCustomerConversation(
            conversationId,
            conversationDetail.data.version,
          )
        : releaseCustomerConversation(conversationId);
    },
    onSuccess: (_result, action) => {
      message.success(action === "takeover" ? "会话已接管" : "会话已释放");
      if (action === "takeover") {
        window.setTimeout(() => {
          ticketPanelRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        }, 150);
      }
    },
    onError: (error: Error) => {
      if (error instanceof ApiError) {
        if (error.code === "AGENT_CAPACITY_REACHED") {
          message.warning(
            `当前客服已负责 ${currentAgentCapacity} 个活动会话，请先释放一个会话。`,
          );
          return;
        }
        if (
          error.code === "CONVERSATION_VERSION_CONFLICT" ||
          error.code === "CONVERSATION_ALREADY_ASSIGNED"
        ) {
          message.warning("会话状态已变化，已为你刷新最新状态。");
          return;
        }
      }
      message.error(error.message);
    },
    onSettled: () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-conversations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-assignment-queue"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-agent-presence"],
        }),
      ]);
    },
  });
  const autoAssign = useMutation({
    mutationFn: autoAssignCustomerConversations,
    onSuccess: async (result) => {
      setAssignmentResult(result);
      message.success(
        `自动分配 ${result.assigned_count} 个会话，剩余 ${result.unassigned_count} 个`,
      );
      await queryClient.invalidateQueries({
        queryKey: ["customer-assignment-queue"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["customer-conversations"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const acknowledgeNotification = useMutation({
    mutationFn: acknowledgeCustomerServiceNotification,
    onSuccess: async () => {
      message.success("主管告警已确认");
      await queryClient.invalidateQueries({
        queryKey: ["customer-service-notifications"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const decideApproval = useMutation({
    mutationFn: (input: {
      approval: McpToolApproval;
      decision: "APPROVE" | "REJECT";
    }) =>
      decideMcpToolApproval(input.approval.id, {
        decision: input.decision,
        expectedVersion: input.approval.version,
        note: approvalNote.trim(),
      }),
    onSuccess: async (approval) => {
      setApprovalDecision(null);
      setApprovalNote("");
      message.success(
        approval.status === "SUCCEEDED"
          ? "审批通过，写工具已执行一次"
          : approval.status === "REJECTED"
            ? "审批已拒绝，写工具未执行"
            : `审批已处理：${approvalStatusLabels[approval.status] ?? approval.status}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mcp-tool-approvals"] }),
        queryClient.invalidateQueries({ queryKey: ["tool-calls"] }),
      ]);
    },
    onError: (error: Error) => {
      if (error instanceof ApiError) {
        if (error.code === "MCP_APPROVAL_SELF_APPROVAL_DENIED") {
          message.error("申请人与审批人不能是同一个账号，请更换审批人。");
          return;
        }
        if (error.code === "MCP_APPROVAL_VERSION_CONFLICT") {
          message.warning("审批单状态已变化，请刷新后重新确认。");
          void queryClient.invalidateQueries({
            queryKey: ["mcp-tool-approvals"],
          });
          return;
        }
      }
      message.error(error.message);
    },
  });
  const updateIncident = useMutation({
    mutationFn: (input: {
      incident: McpActionIncident;
      action: "acknowledge" | "resolve";
    }) =>
      actOnMcpActionIncident(input.incident.id, input.action, {
        expectedVersion: input.incident.version,
        note: incidentNote.trim(),
        outcome:
          input.action === "resolve" ? incidentOutcome : undefined,
      }),
    onSuccess: async (incident) => {
      setIncidentDecision(null);
      setIncidentNote("");
      message.success(
        incident.status === "RESOLVED"
          ? "事故已关闭，处理结论已留档"
          : "事故已确认，已分配给当前处理人",
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["mcp-action-incidents"],
        }),
        queryClient.invalidateQueries({ queryKey: ["tool-calls"] }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const reconcileIncident = useMutation({
    mutationFn: (incident: McpActionIncident) =>
      reconcileMcpActionIncident(incident.id, {
        expectedVersion: incident.version,
      }),
    onSuccess: async (incident) => {
      message.success(
        incident.reconciliation_status === "SUCCEEDED"
          ? "对账查询完成，请根据真实结果填写事故结论"
          : "对账失败，请检查只读工具和参数",
      );
      await queryClient.invalidateQueries({
        queryKey: ["mcp-action-incidents"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const requestCompensation = useMutation({
    mutationFn: (incident: McpActionIncident) => {
      let parsedArguments: Record<string, unknown>;
      try {
        parsedArguments = JSON.parse(compensationArguments) as Record<
          string,
          unknown
        >;
      } catch {
        throw new Error("补偿参数必须是合法 JSON 对象");
      }
      return requestMcpActionCompensation(incident.id, {
        expectedVersion: incident.version,
        toolId: compensationToolId.trim() || undefined,
        arguments: parsedArguments,
        note: compensationNote.trim(),
      });
    },
    onSuccess: async (incident) => {
      setCompensationIncident(null);
      setCompensationToolId("");
      setCompensationArguments("{}");
      setCompensationNote("");
      message.success(
        `补偿审批已创建：${incident.compensation_approval_id?.slice(0, 8)}`,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["mcp-action-incidents"],
        }),
        queryClient.invalidateQueries({ queryKey: ["mcp-tool-approvals"] }),
      ]);
    },
    onError: (error: Error) => message.error(error.message),
  });
  const manualReply = useMutation({
    mutationFn: (resolve: boolean) => {
      if (!conversationId) throw new Error("请先选择一个会话");
      if (conversationDetail.data?.assigned_agent_id !== currentAgentId) {
        throw new Error("请先接管会话，再进行人工回复");
      }
      if (!manualReplyText.trim()) {
        throw new Error("请输入人工回复内容");
      }
      return sendManualCustomerReply(
        conversationId,
        manualReplyText.trim(),
        resolve,
      );
    },
    onSuccess: (_conversation, resolve) => {
      setManualReplyText("");
      message.success(resolve ? "回复已发送，会话已解决" : "人工回复已发送");
    },
    onError: (error: Error) => message.error(error.message),
    onSettled: () => {
      void Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["customer-conversation", conversationId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ticket", ticketId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-conversations"],
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-assignment-queue"],
        }),
      ]);
    },
  });
  const logistics = useMutation({
    mutationFn: () => {
      if (!logisticsOrderId.trim() && !trackingNumber.trim()) {
        throw new Error("请输入订单号或运单号");
      }
      return queryLogistics({
        orderId: logisticsOrderId.trim(),
        trackingNumber: trackingNumber.trim(),
        carrierCode: carrierCode.trim(),
      });
    },
    onError: (error: Error) => {
      if (
        error instanceof ApiError &&
        error.code === "LOGISTICS_PROVIDER_NOT_CONFIGURED"
      ) {
        message.warning("物流查询接口尚未配置，系统不会生成虚假物流状态。");
        return;
      }
      message.error(error.message);
    },
  });
  const replySuggestion = useMutation({
    mutationFn: (_options?: { silent?: boolean }) => {
      if (!conversationId) throw new Error("请先选择一个会话");
      return generateCustomerReplySuggestion(conversationId);
    },
    onSuccess: (suggestion, options) => {
      setManualReplyText(suggestion.text);
      setAutoSuggestionError("");
      if (!options?.silent) {
        message.success(
          suggestion.fallback_used
            ? "已重新生成建议，但模型调用失败，当前为本地规则建议"
            : "AI 回复草稿已重新生成，请确认后发送",
        );
      }
    },
    onError: (error: Error, options) => {
      setAutoSuggestionError(error.message);
      if (!options?.silent) {
        message.error(error.message);
      }
    },
  });
  const optimizeReply = useMutation({
    mutationFn: () => {
      if (!conversationId) throw new Error("请先选择一个会话");
      if (!manualReplyText.trim()) throw new Error("请先输入或生成回复内容");
      return optimizeCustomerReply(
        conversationId,
        manualReplyText.trim(),
        optimizationStyle,
      );
    },
    onSuccess: (result) => {
      setManualReplyText(result.text);
      message.success("AI 已优化当前回复，请确认后再发送");
    },
    onError: (error: Error) => message.error(error.message),
  });

  const ticket = detail.data;
  const pendingReview = ticket?.workflow_state === "PENDING_REVIEW";
  const conversationItems = conversations.data?.items ?? [];
  const filteredConversations = useMemo(() => {
    if (conversationFilter === "review") {
      return conversationItems.filter(
        (conversation) =>
          conversation.current_workflow_state === "PENDING_REVIEW",
      );
    }
    if (conversationFilter === "human") {
      return conversationItems.filter(
        (conversation) => conversation.current_needs_human,
      );
    }
    if (conversationFilter === "mine") {
      return conversationItems.filter(
        (conversation) =>
          Boolean(currentAgentId) &&
          conversation.assigned_agent_id === currentAgentId,
      );
    }
    if (conversationFilter === "completed") {
      return conversationItems.filter(
        (conversation) =>
          conversation.current_workflow_state === "COMPLETED",
      );
    }
    return conversationItems;
  }, [conversationFilter, conversationItems, currentAgentId]);
  const assignedAgentId = conversationDetail.data?.assigned_agent_id;
  const currentAgentLoad = conversationItems.filter(
    (conversation) =>
      conversation.status === "ACTIVE" &&
      Boolean(currentAgentId) &&
      conversation.assigned_agent_id === currentAgentId,
  ).length;
  const currentAgentCapacity =
    presence.data?.items.find(
      (agent) => agent.agent_id === currentAgentId,
    )?.max_conversations ?? 5;
  const capacityReached =
    Boolean(currentAgentId) &&
    currentAgentLoad >= currentAgentCapacity;
  const assignedToAnotherAgent = Boolean(
    assignedAgentId && (!currentAgentId || assignedAgentId !== currentAgentId),
  );
  const cannotTakeOver = !assignedAgentId && capacityReached;
  const ticketCompleted = ticket?.workflow_state === "COMPLETED";
  const logisticsConfigured =
    runtime.data?.logistics_query_provider !== "none" &&
    Boolean(runtime.data?.logistics_query_url_configured);
  const manualStep = ticketCompleted
    ? 3
    : assignedAgentId === currentAgentId
      ? 2
      : 1;
  const displayedMessages =
    conversationDetail.data?.messages.map((message) => ({
      role: message.role,
      text: message.content,
    })) ?? history;
  const conversationMessages = conversationDetail.data?.messages ?? [];
  const currentTicketId = conversationDetail.data?.current_ticket_id;
  const visibleConversationMessages =
    conversationMessages.length > 0
      ? conversationMessages.filter(
          (message) =>
            historyScope === "all" ||
            !currentTicketId ||
            message.ticket_id === currentTicketId,
        )
      : [];
  const historyEntries =
    conversationMessages.length > 0
      ? visibleConversationMessages.map((message) => {
          const human =
            message.role === "ASSISTANT" &&
            message.created_by !== "digital_employee";
          return {
            id: message.id,
            role: message.role,
            text: message.content,
            createdAt: message.created_at,
            ticketId: message.ticket_id,
            createdBy: message.created_by,
            senderLabel:
              message.role === "BUYER"
                ? "买家"
                : human
                  ? `人工客服 · ${message.created_by}`
                  : "数字员工",
            human,
          };
        })
      : history.map((turn, index) => ({
          id: `draft-history-${index}`,
          role: turn.role,
          text: turn.text,
          createdAt: null,
          ticketId: null,
          createdBy: null,
          senderLabel: turn.role === "BUYER" ? "买家" : "数字员工",
          human: false,
        }));
  const currentTicketMessageCount = conversationMessages.filter(
    (message) =>
      !currentTicketId || message.ticket_id === currentTicketId,
  ).length;
  const latestBuyerMessage = [...conversationMessages]
    .reverse()
    .find(
      (message) =>
        message.role === "BUYER" &&
        (!currentTicketId || message.ticket_id === currentTicketId),
    );
  const autoSuggestionKey =
    conversationId && currentTicketId && latestBuyerMessage
      ? `${conversationId}:${currentTicketId}:${latestBuyerMessage.id}`
      : "";
  const guidedStep = ticketCompleted
    ? 3
    : assignedAgentId === currentAgentId
      ? 2
      : conversationId
        ? 1
        : 0;
  const guidedScenarios = [
    {
      key: "presales",
      emoji: "🛍️",
      title: "商品咨询",
      description: "查看知识库回答与商品引用",
      subject: "保温杯材质和保温时长咨询",
      body: "你好，这款保温杯是什么材质，能保温多久？",
      tag: "低风险",
      color: "green",
    },
    {
      key: "logistics",
      emoji: "🚚",
      title: "物流查询",
      description: "体验实时 MCP 工具与工具审计",
      subject: "订单物流进度查询",
      body: "我的订单 DEMO-ORDER-1001 到哪了？请查询实时物流状态。",
      tag: "只读工具",
      color: "blue",
    },
    {
      key: "refund",
      emoji: "🛡️",
      title: "退款审批",
      description: "体验风险判断、写审批和人工接管",
      subject: "保温杯破损退款申请",
      body: "订单 DEMO-ORDER-2001 的保温杯破损，申请退款 59.9 元，请走人工审批。",
      tag: "高风险",
      color: "volcano",
    },
  ] as const;
  const runGuidedScenario = (scenario: (typeof guidedScenarios)[number]) => {
    if (!employeeId) {
      message.warning("数字员工仍在加载，请稍后再试");
      return;
    }
    setSubject(scenario.subject);
    setBody(scenario.body);
    setManualReplyText("");
    setHistory([]);
    setConversationId("");
    setTicketId("");
    createTicket.mutate({
      subject: scenario.subject,
      body: scenario.body,
      newConversation: true,
      autoRoute: true,
    });
  };

  useEffect(() => {
    if (!followLatest) return;
    const frame = window.requestAnimationFrame(() => {
      const container = historyContainerRef.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    conversationId,
    followLatest,
    historyEntries.length,
    historyScope,
  ]);

  useEffect(() => {
    if (
      !autoSuggestionKey ||
      !conversationDetail.data ||
      ticket?.workflow_state === "COMPLETED" ||
      ticket?.workflow_state === "FAILED_TERMINAL"
    ) {
      return;
    }
    if (lastAutoSuggestionKeyRef.current === autoSuggestionKey) return;
    lastAutoSuggestionKeyRef.current = autoSuggestionKey;
    setAutoSuggestionError("");
    replySuggestion.mutate({ silent: true });
  }, [
    autoSuggestionKey,
    conversationDetail.data,
    replySuggestion,
    ticket?.workflow_state,
  ]);

  useEffect(() => {
    if (!scrollToTicketOnLoad || !ticket) return;
    const frame = window.requestAnimationFrame(() => {
      ticketPanelRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      setScrollToTicketOnLoad(false);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [conversationId, scrollToTicketOnLoad, ticket]);

  const selectConversation = (
    selectedConversationId: string,
    selectedTicketId: string | null,
  ) => {
    setConversationId(selectedConversationId);
    setTicketId(selectedTicketId ?? "");
    setScrollToTicketOnLoad(true);
  };

  if (viewMode === "chat") {
    return (
      <CustomerChatDemo
        key={demoScenario}
        scenario={demoScenario}
        technicalMode={technicalMode}
        onOpenWorkspace={(selectedConversationId) => {
          const params = new URLSearchParams({
            scenario: demoScenario,
          });
          if (selectedConversationId) {
            params.set("conversation", selectedConversationId);
          }
          const path = `/customer-service/workbench?${params.toString()}`;
          if (onNavigate) {
            onNavigate(path);
          } else {
            window.history.replaceState({}, "", path);
            setViewMode("workspace");
          }
        }}
        onOpenAdmin={
          technicalMode
            ? () =>
                onNavigate
                  ? onNavigate("/customer-service/admin")
                  : setViewMode("admin")
            : undefined
        }
      />
    );
  }

  if (viewMode === "workspace") {
    const requestedConversationId =
      new URLSearchParams(window.location.search).get("conversation") ??
      "";
    return (
      <CustomerServiceWorkbench
        technicalMode={technicalMode}
        initialConversationId={
          requestedConversationId || conversationId
        }
        onOpenChat={(selectedConversationId) => {
          const params = new URLSearchParams({
            scenario: demoScenario,
          });
          if (selectedConversationId) {
            params.set("conversation", selectedConversationId);
          }
          const path = `/customer-service?${params.toString()}`;
          if (onNavigate) {
            onNavigate(path);
          } else {
            window.history.replaceState({}, "", path);
            setViewMode("chat");
          }
        }}
        onOpenAdmin={
          canOpenAdmin
            ? () =>
                onNavigate
                  ? onNavigate("/customer-service/admin")
                  : setViewMode("admin")
            : undefined
        }
        onOpenApprovals={() =>
          onNavigate
            ? onNavigate(
                `/customer-service/approvals${
                  requestedConversationId
                    ? `?conversation=${encodeURIComponent(requestedConversationId)}`
                    : ""
                }`,
              )
            : setViewMode("workspace")
        }
      />
    );
  }

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>
            {section === "approvals"
              ? "待审批操作"
              : section === "incidents"
                ? "执行异常"
                : "运营看板"}
          </Title>
          <Paragraph type="secondary">
            {section === "approvals"
              ? "处理退款、取消、发布等需要人工确认的外部业务动作。"
              : section === "incidents"
                ? "处理执行失败或结果未知的外部操作，先对账再决定后续动作。"
                : "查看客服负载、风险、近期趋势、告警和待接管队列。"}
          </Paragraph>
        </div>
        <Space wrap>
          {!onNavigate && (
            <Segmented
              value={viewMode}
              onChange={(value) =>
                setViewMode(value as CustomerServiceSurfaceMode)
              }
              options={[
                { label: "聊天演示", value: "chat" },
                { label: "日常会话", value: "workspace" },
                ...(technicalMode
                  ? [{ label: "运营看板", value: "admin" }]
                  : []),
              ]}
            />
          )}
        </Space>
      </div>

      <Alert
        type="warning"
        showIcon
        message="这里演示的是客户服务沙盒"
        description="测试问题只写入当前演示环境的会话和工单。企业消息渠道与外部业务系统消息渠道均未连接生产系统，不会发送给真实用户、员工或业务系统。"
      />

      {section !== "chat" && (
        <Alert
          type="info"
          showIcon
          message="这三个页面分别做什么"
          description={
            <Space direction="vertical" size={2}>
              <Text>
                运营看板：看整体结果、趋势、告警和待接管排队，不处理具体会话。
              </Text>
              <Text>
                待审批操作：处理尚未执行、需要人工确认的退款、取消或发布。
              </Text>
              <Text>
                执行异常：处理已经失败或结果不确定的外部操作，先对账再关闭。
              </Text>
            </Space>
          }
        />
      )}

      {viewMode === "guide" && (
        <Card
          className="section-card"
          title="第一次使用？按这 4 步完成一次测试"
          extra={
            <Button
              onClick={() => setViewMode("workspace")}
            >
              查看全部会话
            </Button>
          }
        >
          <Steps
            current={guidedStep}
            items={[
              {
                title: "发起测试问题",
                description: "任选下面一个场景",
              },
              {
                title: "自动分配",
                description: "系统按技能与负载派给你",
              },
              {
                title: "生成或修改回复",
                description: "确认后才会发送",
              },
              {
                title: "标记解决",
                description: "完成一次闭环",
              },
            ]}
          />
          <Alert
            style={{ marginTop: 20 }}
            type="info"
            showIcon
            message={
              guidedStep === 0
                ? "当前下一步：选一个场景，系统会自动创建测试会话"
                : guidedStep === 1
                  ? "当前下一步：系统等待符合条件的在线坐席；若你是兜底人员，也可手动接管"
                  : guidedStep === 2
                    ? "系统已将会话分配给你，AI 草稿也已自动生成；确认内容后即可发送"
                    : "当前会话已解决，可以从场景卡片重新开始"
            }
            description={
              <Space wrap>
                <Text>
                  数字员工负责自动分析；你负责确认、改写和承担最终结果。
                </Text>
                {guidedStep === 1 && (
                  <Button
                    type="primary"
                    loading={assignment.isPending}
                    onClick={() => assignment.mutate("takeover")}
                  >
                    接管当前会话
                  </Button>
                )}
                {guidedStep === 2 && (
                  <Button
                    onClick={() =>
                      ticketPanelRef.current?.scrollIntoView({
                        behavior: "smooth",
                        block: "start",
                      })
                    }
                  >
                    进入当前处理区
                  </Button>
                )}
              </Space>
            }
          />
          <Row gutter={[12, 12]} style={{ marginTop: 20 }}>
            {guidedScenarios.map((scenario) => (
              <Col xs={24} lg={8} key={scenario.key}>
                <Card
                  hoverable
                  size="small"
                  onClick={() => runGuidedScenario(scenario)}
                  style={{ height: "100%", cursor: "pointer" }}
                >
                  <Space direction="vertical" size={8}>
                    <Space>
                      <span style={{ fontSize: 24 }}>{scenario.emoji}</span>
                      <Text strong>{scenario.title}</Text>
                      <Tag color={scenario.color}>{scenario.tag}</Tag>
                    </Space>
                    <Text type="secondary">{scenario.description}</Text>
                    <Text ellipsis style={{ maxWidth: 320 }}>
                      “{scenario.body}”
                    </Text>
                    <Button
                      type={scenario.key === "presales" ? "primary" : "default"}
                      loading={createTicket.isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        runGuidedScenario(scenario);
                      }}
                    >
                      用这个场景开始
                    </Button>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
          <Alert
            style={{ marginTop: 16 }}
            type="success"
            showIcon
            message="看不懂这些词？"
            description="接管：锁定由你处理，避免多人抢同一会话。回复建议：只是草稿，不会自动发给用户。审批：退款、取消等写操作必须先由另一名主管或管理员确认。"
          />
        </Card>
      )}

      {viewMode === "guide" && (
        <Card
          className="section-card"
          title="或自定义一个测试问题"
          extra={
            <Text type="secondary">
              提交后自动跳到当前会话
            </Text>
          }
        >
          <Form layout="vertical">
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="新手模式已使用默认数字员工和当前业务场景"
              description="只填写问题和内容即可。需要切换员工或业务场景时，进入“日常会话”或“运营看板”。"
            />
            <Form.Item label="问题标题">
              <Input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
              />
            </Form.Item>
            <Form.Item label="问题内容">
              <TextArea
                rows={4}
                value={body}
                onChange={(event) => setBody(event.target.value)}
              />
            </Form.Item>
            <Space wrap>
              <Button
                type="primary"
                loading={createTicket.isPending}
                disabled={!subject.trim() || !body.trim()}
                onClick={() =>
                  createTicket.mutate({
                    subject,
                    body,
                    autoRoute: true,
                  })
                }
              >
                {displayedMessages.length ? "继续提问" : "提交给数字员工"}
              </Button>
            </Space>
          </Form>
        </Card>
      )}

      {viewMode === "admin" && section === "admin" && (
        <>
      <Row gutter={[12, 12]}>
        {[
          ["活动会话", metrics.data?.active_conversations ?? 0],
          ["待接管", metrics.data?.unassigned_conversations ?? 0],
          ["在线客服", metrics.data?.online_agents ?? 0],
          ["SLA 超时", metrics.data?.sla_overdue ?? 0],
          ["主管告警", metrics.data?.open_supervisor_notifications ?? 0],
          [
            "平均等待",
            `${Math.floor((metrics.data?.average_waiting_seconds ?? 0) / 60)} 分钟`,
          ],
        ].map(([label, value]) => (
          <Col xs={12} md={8} xl={4} key={String(label)}>
            <Card size="small">
              <Statistic title={label} value={value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        size="small"
        title="活动会话风险分布"
        extra={
          <Text type="secondary">
            待评估 {metrics.data?.risk_counts?.UNKNOWN ?? 0} · 风险决定授权边界，
            优先级决定处理时效
          </Text>
        }
      >
        <Row gutter={[12, 12]}>
          {riskLevels.map((level) => (
            <Col xs={12} xl={6} key={level.code}>
              <Card size="small" className="metric-card">
                <Space direction="vertical" size={4}>
                  <Space>
                    <Tag color={level.color}>{level.code}</Tag>
                    <Text strong>{level.label}</Text>
                  </Space>
                  <Title level={3} style={{ margin: 0 }}>
                    {metrics.data?.risk_counts?.[level.code] ?? 0}
                  </Title>
                  <Text type="secondary">{level.description}</Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
        </>
      )}

      {viewMode === "admin" && section === "admin" && (
      <Card
        size="small"
        title="近 7 天客服趋势"
        extra={
          <Text type="secondary">
            平均首响{" "}
            {historyMetrics.data?.average_first_response_seconds == null
              ? "-"
              : `${historyMetrics.data.average_first_response_seconds} 秒`}
          </Text>
        }
      >
        <Table
          rowKey="date"
          size="small"
          loading={historyMetrics.isLoading}
          dataSource={historyMetrics.data?.daily}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          columns={[
            { title: "日期", dataIndex: "date" },
            { title: "新增会话", dataIndex: "conversations_created" },
            { title: "消息", dataIndex: "messages" },
            { title: "买家消息", dataIndex: "buyer_messages" },
            { title: "员工消息", dataIndex: "assistant_messages" },
            {
              title: "平均首响",
              dataIndex: "average_first_response_seconds",
              render: (value: number | null) =>
                value == null ? "-" : `${value} 秒`,
            },
          ]}
        />
      </Card>
      )}

      {section === "admin" && (serviceAlerts.data?.total ?? 0) > 0 && (
        <Alert
          type="error"
          showIcon
          message={`${serviceAlerts.data?.total} 个会话已超过 SLA`}
          description={serviceAlerts.data?.items
            .slice(0, 3)
            .map(
              (item) =>
                `${item.requester_ref} · ${item.priority} · 超时 ${Math.floor(
                  item.overdue_seconds / 60,
                )} 分钟`,
            )
            .join("；")}
        />
      )}
      {section === "admin" &&
        (notifications.data?.items.filter((item) => item.status === "OPEN")
          .length ??
          0) > 0 && (
        <Alert
          type="warning"
          showIcon
          message="主管待确认告警"
          description={
            notifications.data?.items.find((item) => item.status === "OPEN")
              ?.message
          }
          action={
            <Button
              size="small"
              loading={acknowledgeNotification.isPending}
              onClick={() => {
                const first = notifications.data?.items.find(
                  (item) => item.status === "OPEN",
                );
                if (first) acknowledgeNotification.mutate(first.id);
              }}
            >
              确认
            </Button>
          }
        />
      )}

      {viewMode === "admin" && section === "approvals" && (
      <Card
        title="待审批的外部操作"
        extra={
          <Space wrap>
            <Tag color="gold">
              {approvalFilter === "PENDING" ? "待审批" : "当前"}{" "}
              {mcpApprovals.data?.total ?? 0}
            </Tag>
            <Segmented
              size="small"
              value={approvalFilter}
              onChange={(value) => setApprovalFilter(String(value))}
              options={[
                { label: "待审批", value: "PENDING" },
                { label: "成功", value: "SUCCEEDED" },
                { label: "拒绝", value: "REJECTED" },
                { label: "全部", value: "ALL" },
              ]}
            />
          </Space>
        }
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="这里只处理需要人工确认的外部动作"
          description="退款、取消、发送、发布等操作不会由数字员工直接执行。确认后系统只执行一次；普通回复审核请在工作台对话气泡中完成。"
        />
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          审批身份来自页面右上角的测试身份或 OIDC 登录身份；审批人必须与申请人不同。
        </Text>
        <Table
          rowKey="id"
          size="small"
          loading={mcpApprovals.isLoading}
          dataSource={mcpApprovals.data?.items ?? []}
          pagination={{ pageSize: 5, showSizeChanger: false }}
          locale={{ emptyText: "当前筛选下没有待审批的外部操作" }}
          onRow={(record) => ({
            onClick: () => {
              if (record.conversation_id) {
                selectConversation(record.conversation_id, record.ticket_id);
              }
            },
            style: {
              cursor: record.conversation_id ? "pointer" : "default",
            },
          })}
          columns={[
            {
              title: "写工具",
              dataIndex: "tool_id",
              width: 220,
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{value}</Text>
                  <Text type="secondary" ellipsis style={{ maxWidth: 210 }}>
                    {JSON.stringify(record.arguments)}
                  </Text>
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (value: string) => (
                <Tag color={approvalStatusColor(value)}>
                  {approvalStatusLabels[value] ?? "未知状态"}
                </Tag>
              ),
            },
            {
              title: "关联工单",
              dataIndex: "ticket_id",
              width: 130,
              render: (value: string | null) =>
                value ? (
                  <Text code>{value.slice(0, 8)}</Text>
                ) : (
                  <Text type="secondary">无</Text>
                ),
            },
            {
              title: "申请信息",
              dataIndex: "requested_by",
              width: 190,
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text>{value}</Text>
                  <Text type="secondary">
                    {new Date(record.created_at).toLocaleString("zh-CN")}
                  </Text>
                </Space>
              ),
            },
            {
              title: "原因与结果",
              dataIndex: "reason",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text ellipsis style={{ maxWidth: 260 }}>
                    {value || "模型未提供原因"}
                  </Text>
                  {record.decision_note && (
                    <Text type="secondary">
                      审批意见：{record.decision_note}
                    </Text>
                  )}
                  {record.error_message && (
                    <Text type="danger">{record.error_message}</Text>
                  )}
                  {String(record.result.text ?? "") && (
                    <Text type="success" ellipsis style={{ maxWidth: 260 }}>
                      结果：{String(record.result.text)}
                    </Text>
                  )}
                  <Tag
                    color={
                      record.required_role === "admin" ? "red" : "blue"
                    }
                  >
                    {record.required_role === "admin"
                      ? "需要管理员审批"
                      : "主管可审批"}
                  </Tag>
                </Space>
              ),
            },
            {
              title: "操作",
              key: "actions",
              width: 150,
              render: (_value, record) =>
                record.status === "PENDING" ? (
                  <Space
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Button
                      type="primary"
                      size="small"
                      danger
                      onClick={() => {
                        setApprovalNote("");
                        setApprovalDecision({
                          approval: record,
                          decision: "APPROVE",
                        });
                      }}
                    >
                      审批并执行
                    </Button>
                    <Button
                      size="small"
                      onClick={() => {
                        setApprovalNote("");
                        setApprovalDecision({
                          approval: record,
                          decision: "REJECT",
                        });
                      }}
                    >
                      拒绝
                    </Button>
                  </Space>
                ) : (
                  <Text type="secondary">
                    {record.decided_by
                      ? `审批人 ${record.decided_by}`
                      : "无需操作"}
                  </Text>
                ),
            },
          ]}
        />
      </Card>
      )}

      {viewMode === "admin" && section === "incidents" && (
      <Card
        title="执行失败或结果异常"
        extra={
          <Space wrap>
            <Tag color="red">
              {incidentFilter === "OPEN" ? "待处理" : "当前"}{" "}
              {mcpIncidents.data?.total ?? 0}
            </Tag>
            <Segmented
              size="small"
              value={incidentFilter}
              onChange={(value) => setIncidentFilter(String(value))}
              options={[
                { label: "待处理", value: "OPEN" },
                { label: "处理中", value: "ACKNOWLEDGED" },
                { label: "已关闭", value: "RESOLVED" },
                { label: "全部", value: "ALL" },
              ]}
            />
          </Space>
        }
      >
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="这个页面只处理结果不确定的外部动作"
          description="超时或连接中断时，外部系统可能已经执行。必须先在订单、资金或渠道系统核对真实结果，再关闭异常或申请补偿；系统不会自动重复执行。"
        />
        <Table
          rowKey="id"
          size="small"
          loading={mcpIncidents.isLoading}
          dataSource={mcpIncidents.data?.items ?? []}
          pagination={{ pageSize: 5, showSizeChanger: false }}
          locale={{ emptyText: "当前筛选下没有执行异常" }}
          onRow={(record) => ({
            onClick: () => {
              if (record.conversation_id) {
                selectConversation(record.conversation_id, record.ticket_id);
              }
            },
            style: {
              cursor: record.conversation_id ? "pointer" : "default",
            },
          })}
          columns={[
            {
              title: "工具与失败分类",
              dataIndex: "tool_id",
              width: 240,
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{value}</Text>
                  <Tag color="volcano">
                    {incidentFailureLabels[record.failure_class] ??
                      record.failure_class}
                  </Tag>
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (value: string) => (
                <Tag color={value === "OPEN" ? "red" : value === "RESOLVED" ? "green" : "gold"}>
                  {incidentStatusLabels[value] ?? "未知状态"}
                </Tag>
              ),
            },
            {
              title: "错误",
              dataIndex: "error_message",
              render: (value: string | null, record) => (
                <Space direction="vertical" size={0}>
                  <Text code>{record.error_code ?? "-"}</Text>
                  <Text type="danger" ellipsis style={{ maxWidth: 280 }}>
                    {value ?? "无错误详情"}
                  </Text>
                </Space>
              ),
            },
            {
              title: "处理要求与结论",
              dataIndex: "required_action",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text ellipsis style={{ maxWidth: 360 }}>
                    {value}
                  </Text>
                  {record.assigned_to && (
                    <Text type="secondary">
                      处理人：{record.assigned_to}
                    </Text>
                  )}
                  <Tag
                    color={
                      record.reconciliation_status === "SUCCEEDED"
                        ? "green"
                        : record.reconciliation_status === "FAILED"
                          ? "red"
                          : "default"
                    }
                  >
                    对账：
                    {reconciliationStatusLabels[
                      record.reconciliation_status
                    ] ?? record.reconciliation_status}
                  </Tag>
                  {record.reconciliation_tool_id && (
                    <Text type="secondary">
                      工具：{record.reconciliation_tool_id}
                    </Text>
                  )}
                  {String(record.reconciliation_result.text ?? "") && (
                    <Text type="success" ellipsis style={{ maxWidth: 360 }}>
                      对账结果：{String(record.reconciliation_result.text)}
                    </Text>
                  )}
                  <Tag
                    color={
                      record.compensation_status === "SUCCEEDED"
                        ? "green"
                        : record.compensation_status === "FAILED"
                          ? "red"
                          : record.compensation_status === "PENDING_APPROVAL"
                            ? "gold"
                            : "default"
                    }
                  >
                    补偿：
                    {compensationStatusLabels[record.compensation_status] ??
                      record.compensation_status}
                  </Tag>
                  {record.resolution_note && (
                    <Text type="success">
                      结论：{record.resolution_note}
                    </Text>
                  )}
                </Space>
              ),
            },
            {
              title: "操作",
              key: "actions",
              width: 180,
              render: (_value, record) =>
                record.status !== "RESOLVED" ? (
                  <Space
                    direction="vertical"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {record.status === "OPEN" && (
                      <Button
                        size="small"
                        onClick={() => {
                          setIncidentNote("");
                          setIncidentDecision({
                            incident: record,
                            action: "acknowledge",
                          });
                        }}
                      >
                        确认处理
                      </Button>
                    )}
                    {record.reconciliation_status !== "SUCCEEDED" && (
                      <Button
                        size="small"
                        loading={reconcileIncident.isPending}
                        onClick={() =>
                          reconcileIncident.mutate(record)
                        }
                      >
                        立即对账
                      </Button>
                    )}
                    {record.reconciliation_status === "SUCCEEDED" &&
                      !["PENDING_APPROVAL", "EXECUTING", "SUCCEEDED"].includes(
                        record.compensation_status,
                      ) && (
                        <Button
                          size="small"
                          danger
                          onClick={() => {
                            setCompensationIncident(record);
                            setCompensationToolId("");
                            setCompensationArguments(
                              JSON.stringify(
                                record.reconciliation_arguments,
                                null,
                                2,
                              ),
                            );
                            setCompensationNote("");
                          }}
                        >
                          申请补偿
                        </Button>
                      )}
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => {
                        setIncidentNote(record.resolution_note ?? "");
                        setIncidentOutcome("INCONCLUSIVE");
                        setIncidentDecision({
                          incident: record,
                          action: "resolve",
                        });
                      }}
                    >
                      关闭事故
                    </Button>
                  </Space>
                ) : (
                  <Text type="secondary">已闭环</Text>
                ),
            },
          ]}
        />
      </Card>
      )}

      {section === "chat" &&
        viewMode === "admin" && (
      <>
      <div ref={conversationListRef} style={{ scrollMarginTop: 16 }}>
        <Card
          title="会话列表"
          extra={
            <Space>
              <Tag color="green">在线客服 {presence.data?.online_count ?? 0}</Tag>
              <Text type="secondary">
                {conversations.data?.total ?? 0} 个会话
              </Text>
            </Space>
          }
        >
        <Segmented
          block
          value={conversationFilter}
          onChange={(value) =>
            setConversationFilter(value as ConversationFilter)
          }
          options={[
            { label: `全部 ${conversationItems.length}`, value: "all" },
            {
              label: `等待审核 ${
                conversationItems.filter(
                  (item) => item.current_workflow_state === "PENDING_REVIEW",
                ).length
              }`,
              value: "review",
            },
            {
              label: `等待人工 ${
                conversationItems.filter((item) => item.current_needs_human)
                  .length
              }`,
              value: "human",
            },
            {
              label: `我负责 ${
                conversationItems.filter(
                  (item) =>
                    Boolean(currentAgentId) &&
                    item.assigned_agent_id === currentAgentId,
                ).length
              }`,
              value: "mine",
            },
            {
              label: `已处理完成 ${
                conversationItems.filter(
                  (item) => item.current_workflow_state === "COMPLETED",
                ).length
              }`,
              value: "completed",
            },
          ]}
          style={{ marginBottom: 12 }}
        />
        <Table
          rowKey="id"
          size="small"
          loading={conversations.isLoading}
          dataSource={filteredConversations}
          pagination={{ pageSize: 6, showSizeChanger: false }}
          locale={{ emptyText: "当前筛选下暂无客服会话" }}
          onRow={(record) => ({
            onClick: () => {
              selectConversation(record.id, record.current_ticket_id);
            },
            style: {
              cursor: "pointer",
              background:
                record.id === conversationId ? "#e6f4ff" : undefined,
            },
          })}
          columns={[
            {
              title: "买家",
              dataIndex: "requester_ref",
              render: (value: string, record) => (
                <Space direction="vertical" size={0}>
                  <Text strong>{value}</Text>
                  <Text type="secondary">{record.id.slice(0, 8)}</Text>
                </Space>
              ),
            },
            {
              title: "当前工单",
              dataIndex: "current_workflow_state",
              width: 130,
              render: (value: string | null) =>
                value ? (
                  <Tag color={workflowColor(value)}>
                    {localizedLabel(workflowStateLabels, value)}
                  </Tag>
                ) : (
                  <Tag>尚未生成</Tag>
                ),
            },
            {
              title: "风险",
              dataIndex: "current_risk_level",
              width: 80,
              render: (value: string | null) => (
                <Tag color={riskColor(value)}>{value ?? "待评估"}</Tag>
              ),
            },
            {
              title: "优先级",
              dataIndex: "current_priority",
              width: 80,
              render: (value: string | null) => value ?? "-",
            },
            {
              title: "负责人",
              dataIndex: "assigned_agent_id",
              width: 130,
              render: (value: string | null) =>
                value === currentAgentId && value ? (
                  <Tag color="green">我负责</Tag>
                ) : (
                  <Tag>{value ?? "未接管"}</Tag>
                ),
            },
            {
              title: "消息",
              dataIndex: "messages",
              width: 70,
              render: (value: unknown[]) => value.length,
            },
            {
              title: "会话",
              dataIndex: "status",
              width: 90,
              render: (value: string) => (
                <Tag color={value === "ACTIVE" ? "blue" : "default"}>
                  {localizedLabel(conversationStatusLabels, value)}
                </Tag>
              ),
            },
          ]}
        />
        </Card>
      </div>
      </>
      )}

      {section === "admin" && (
      <Card
        title="待接管队列（自动派单兜底）"
        extra={
          <Space>
            <Text type="secondary">
              自动派单运行中 · {assignmentQueue.data?.total ?? 0} 个需兜底
            </Text>
            <Button
              type="primary"
              loading={autoAssign.isPending}
              disabled={!assignmentQueue.data?.total}
              onClick={() => autoAssign.mutate()}
            >
              主管立即补派
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="conversation_id"
          size="small"
          loading={assignmentQueue.isLoading}
          dataSource={assignmentQueue.data?.items}
          pagination={{ pageSize: 5, showSizeChanger: false }}
          locale={{ emptyText: "暂无待接管会话" }}
          onRow={(record) => ({
            onClick: () => {
              selectConversation(
                record.conversation_id,
                record.current_ticket_id,
              );
            },
            style: {
              cursor: "pointer",
              background:
                record.conversation_id === conversationId
                  ? "#e6f4ff"
                  : undefined,
            },
          })}
          columns={[
            { title: "买家", dataIndex: "requester_ref" },
            {
              title: "优先级",
              dataIndex: "priority",
              width: 90,
              render: (value: string) => (
                <Tag color={value === "P0" || value === "P1" ? "red" : "gold"}>
                  {value}
                </Tag>
              ),
            },
            {
              title: "风险",
              dataIndex: "risk_level",
              width: 90,
              render: (value: string | null) => (
                <Tag color={riskColor(value)}>{value ?? "待评估"}</Tag>
              ),
            },
            {
              title: "等待时长",
              dataIndex: "waiting_seconds",
              width: 110,
              render: (value: number) => `${Math.floor(value / 60)} 分钟`,
            },
          ]}
        />
      </Card>
      )}

      {(section === "chat" || viewMode === "guide") &&
        displayedMessages.length > 0 && (
        <Card
          title="会话历史"
          extra={
            <Space>
              {!followLatest && (
                <Button
                  size="small"
                  onClick={() => setFollowLatest(true)}
                >
                  回到最新
                </Button>
              )}
              <Segmented
                size="small"
                value={historyScope}
                onChange={(value) => {
                  setHistoryScope(value as HistoryScope);
                  setFollowLatest(true);
                }}
                options={[
                  {
                    label: `当前工单 ${currentTicketMessageCount}`,
                    value: "current",
                  },
                  {
                    label: `全部历史 ${conversationMessages.length || history.length}`,
                    value: "all",
                  },
                ]}
              />
            </Space>
          }
        >
          <div
            ref={historyContainerRef}
            onScroll={(event) => {
              const container = event.currentTarget;
              const distanceToBottom =
                container.scrollHeight -
                container.scrollTop -
                container.clientHeight;
              setFollowLatest(distanceToBottom < 64);
            }}
            style={{
              maxHeight: "min(60vh, 620px)",
              overflowY: "auto",
              paddingRight: 8,
            }}
          >
            <Space
              direction="vertical"
              size="small"
              style={{ width: "100%" }}
            >
              {historyEntries.map((message, index) => {
                const showTicket =
                  Boolean(message.ticketId) &&
                  message.ticketId !== historyEntries[index - 1]?.ticketId;
                return (
                  <div key={message.id}>
                    {showTicket && (
                      <div style={{ textAlign: "center", margin: "8px 0" }}>
                        <Tag color={message.ticketId === currentTicketId ? "blue" : "default"}>
                          工单 {message.ticketId?.slice(0, 8)}
                          {message.ticketId === currentTicketId
                            ? " · 当前"
                            : ""}
                        </Tag>
                      </div>
                    )}
                    <div
                      style={{
                        display: "flex",
                        justifyContent:
                          message.role === "BUYER" ? "flex-start" : "flex-end",
                      }}
                    >
                      <Card
                        size="small"
                        style={{
                          maxWidth: "82%",
                          background:
                            message.role === "BUYER"
                              ? "#f5f5f5"
                              : message.human
                                ? "#f6ffed"
                                : "#e6f4ff",
                        }}
                      >
                        <Space
                          direction="vertical"
                          size={4}
                          style={{ width: "100%" }}
                        >
                          <Space size={6}>
                            <Text strong>{message.senderLabel}</Text>
                            {message.createdAt && (
                              <Text type="secondary">
                                {new Date(message.createdAt).toLocaleString()}
                              </Text>
                            )}
                          </Space>
                          <Text style={{ whiteSpace: "pre-wrap" }}>
                            {message.text}
                          </Text>
                        </Space>
                      </Card>
                    </div>
                  </div>
                );
              })}
              {historyEntries.length === 0 && (
                <Text type="secondary">当前工单暂无消息</Text>
              )}
            </Space>
          </div>
        </Card>
      )}

      {(section === "chat" || viewMode === "guide") && ticket && (
        <div ref={ticketPanelRef} style={{ scrollMarginTop: 16 }}>
          <Card
            title="当前测试会话处理"
            extra={
              <Space>
                {String(viewMode) !== "guide" && (
                  <Button
                    size="small"
                    onClick={() =>
                      conversationListRef.current?.scrollIntoView({
                        behavior: "smooth",
                        block: "start",
                      })
                    }
                  >
                    返回会话列表
                  </Button>
                )}
                <Tag color={workflowColor(ticket.workflow_state)}>
                  {localizedLabel(workflowStateLabels, ticket.workflow_state)}
                </Tag>
              </Space>
            }
          >
          {String(viewMode) !== "guide" && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="状态怎么看"
              description="等待审核：数字员工回答需要确认；等待人工处理：高风险问题不能自动回复；人工处理中：已有客服负责；已处理完成：这张工单已解决，不再进入待接管队列。"
            />
          )}
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="数字员工">{ticket.employee.name}</Descriptions.Item>
            <Descriptions.Item label="分类">
              {categoryLabels[ticket.classification?.primary ?? ""] ??
                ticket.classification?.primary ??
                "-"}
            </Descriptions.Item>
            {String(viewMode) !== "guide" && (
              <Descriptions.Item label="路由队列">
                {localizedLabel(queueLabels, ticket.routing.queue_id, "未分流")}
              </Descriptions.Item>
            )}
            {String(viewMode) !== "guide" && (
              <Descriptions.Item label="是否需要人工">
                {ticket.needs_human ? "是" : "否"}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="风险等级">
              <Tag color={riskColor(ticket.risk?.level ?? null)}>
                {ticket.risk?.level ?? "未评估"}
              </Tag>
            </Descriptions.Item>
            {String(viewMode) !== "guide" && (
              <Descriptions.Item label="处理优先级">
                {ticket.priority?.level ?? "-"}
              </Descriptions.Item>
            )}
            <Descriptions.Item label="会话负责人">
              {conversationDetail.data?.assigned_agent_id ?? "未接管"}
            </Descriptions.Item>
            {String(viewMode) !== "guide" && (
              <Descriptions.Item label="会话版本">
                {conversationDetail.data?.version ?? "-"}
              </Descriptions.Item>
            )}
          </Descriptions>
          {(() => {
            const outcome = ticketOutcome(ticket);
            const riskDescription =
              riskLevels.find(
                (level) => level.code === ticket.risk?.level,
              )?.description ?? ticket.risk?.level;
            const completed = [
              "已识别买家问题和业务分类",
              ticket.risk?.level
                ? `已完成风险判断：${riskDescription}`
                : null,
              ticket.draft?.citations.length
                ? `已找到 ${ticket.draft.citations.length} 条企业知识依据`
                : null,
              ticket.draft
                ? "已生成可审核的回复草稿"
                : "尚未生成回复草稿",
            ].filter(Boolean);
            return (
              <Card
                size="small"
                title="为什么这样处理"
                extra={
                  <Tag color={outcome.color}>{outcome.title}</Tag>
                }
                style={{ marginTop: 16 }}
              >
                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={8}>
                    <Text strong>数字员工已完成</Text>
                    <Paragraph type="secondary" style={{ marginTop: 8 }}>
                      {completed.join("；")}。
                    </Paragraph>
                  </Col>
                  <Col xs={24} lg={8}>
                    <Text strong>处理结论</Text>
                    <Paragraph style={{ marginTop: 8 }}>
                      {outcome.reason}
                    </Paragraph>
                  </Col>
                  <Col xs={24} lg={8}>
                    <Text strong>下一步</Text>
                    <Paragraph type="secondary" style={{ marginTop: 8 }}>
                      {outcome.nextStep}
                    </Paragraph>
                  </Col>
                </Row>
              </Card>
            );
          })()}
          <Card size="small" title="你的处理区" style={{ marginTop: 16 }}>
            <Steps
              size="small"
              current={manualStep}
              items={[
                { title: "选择会话" },
                { title: "接管会话" },
                { title: "人工回复" },
                { title: "标记解决" },
              ]}
            />
            <Alert
              style={{ marginTop: 16 }}
              type="info"
              showIcon
              message="人工回复写入当前沙盒会话"
              description="回复只记录为演示环境的人工客服消息；企业消息渠道与外部业务系统消息渠道尚未连接生产系统，不会发送给真实用户、员工或业务系统。"
            />
            {ticketCompleted ? (
              <Space
                direction="vertical"
                size="middle"
                style={{ width: "100%", marginTop: 12 }}
              >
                <Alert
                  type="success"
                  showIcon
                  message="当前工单已解决，无需继续人工处理"
                />
                {assignedAgentId === currentAgentId && (
                  <Button
                    loading={assignment.isPending}
                    onClick={() => assignment.mutate("release")}
                  >
                    释放会话并腾出名额
                  </Button>
                )}
              </Space>
            ) : assignedToAnotherAgent ? (
              <Alert
                style={{ marginTop: 12 }}
                type="warning"
                showIcon
                message={`该会话已由 ${assignedAgentId ?? "其他客服"} 接管`}
                description="不能重复接管；请选择其他待处理会话，或由当前负责人释放后再操作。"
              />
            ) : assignedAgentId === currentAgentId ? (
              <Space
                direction="vertical"
                size="middle"
                style={{ width: "100%", marginTop: 12 }}
              >
                <Space wrap>
                  <Button
                    loading={replySuggestion.isPending}
                    onClick={() =>
                      replySuggestion.mutate({ silent: false })
                    }
                  >
                    重新生成 AI 草稿
                  </Button>
                  <Tag color={replySuggestion.data ? "green" : "blue"}>
                    {replySuggestion.isPending
                      ? "AI 正在自动生成"
                      : replySuggestion.data
                        ? "已自动生成，等待人工确认"
                        : "选中会话后自动生成"}
                  </Tag>
                </Space>
                {replySuggestion.isPending && !replySuggestion.data && (
                  <Alert
                    type="info"
                    showIcon
                    message="正在根据买家问题、知识库和最近会话生成回复草稿…"
                  />
                )}
                {autoSuggestionError && !replySuggestion.isPending && (
                  <Alert
                    type="warning"
                    showIcon
                    message="AI 草稿自动生成失败"
                    description={`${autoSuggestionError}；可以点击“重新生成 AI 草稿”再试。`}
                  />
                )}
                {replySuggestion.data && (
                  <Alert
                    type={replySuggestion.data.fallback_used ? "warning" : "success"}
                    showIcon
                    message={
                      replySuggestion.data.fallback_used
                        ? "模型调用失败，已使用本地规则建议"
                        : `${localizedLabel(
                            providerLabels,
                            replySuggestion.data.provider,
                            "大模型",
                          )} · ${replySuggestion.data.model} · Skill ${
                            replySuggestion.data.skill
                          }`
                    }
                    description={
                      <Space direction="vertical" size={2}>
                        <Text>
                          {replySuggestion.data.citations.length > 0
                            ? `知识依据：${replySuggestion.data.citations
                                .map((citation) => citation.title)
                                .join("、")}`
                            : "本次建议没有知识引用，请谨慎使用。"}
                        </Text>
                        <Text type="secondary">
                          LangGraph：{replySuggestion.data.trace.join(" → ")}
                        </Text>
                        {replySuggestion.data.tool_calls.length > 0 && (
                          <Text type="secondary">
                            MCP 工具：
                            {replySuggestion.data.tool_calls
                              .map(
                                (call) =>
                                  `${call.tool_id}（${call.status}，${call.duration_ms}ms${
                                    call.approval_id
                                      ? `，审批单 ${call.approval_id.slice(0, 8)}${
                                          call.approval_required_role === "admin"
                                            ? "（需管理员）"
                                            : ""
                                        }`
                                      : ""
                                  }）`,
                              )
                              .join("；")}
                          </Text>
                        )}
                        {replySuggestion.data.tool_calls.some(
                          (call) =>
                            call.status === "APPROVAL_REQUIRED" &&
                            call.approval_id,
                        ) && (
                          <Button
                            size="small"
                            type="primary"
                            onClick={() => setViewMode("admin")}
                          >
                            打开审批中心
                          </Button>
                        )}
                      </Space>
                    }
                  />
                )}
                <Space wrap>
                  <Select
                    value={optimizationStyle}
                    onChange={setOptimizationStyle}
                    style={{ width: 130 }}
                    options={[
                      { value: "professional", label: "更专业" },
                      { value: "concise", label: "更简洁" },
                      { value: "empathetic", label: "更亲和" },
                    ]}
                  />
                  <Button
                    loading={optimizeReply.isPending}
                    disabled={!manualReplyText.trim()}
                    onClick={() => optimizeReply.mutate()}
                  >
                    2. 按需优化草稿
                  </Button>
                  <Text type="secondary">
                    只改写现有内容，不新增时效、金额或承诺
                  </Text>
                </Space>
                {optimizeReply.data && (
                  <Alert
                    type="success"
                    showIcon
                    message={`AI 优化完成 · ${optimizeReply.data.model}`}
                    description="优化结果已回填到编辑框，请核对事实后发送。"
                  />
                )}
                <Text strong>人工确认与编辑</Text>
                <TextArea
                  rows={4}
                  value={manualReplyText}
                  onChange={(event) => setManualReplyText(event.target.value)}
                  placeholder="例如：您好，我已经核实订单，正在为您登记退款申请……"
                />
                <Space wrap>
                  <Button
                    type="primary"
                    loading={manualReply.isPending}
                    disabled={!manualReplyText.trim()}
                    onClick={() => manualReply.mutate(true)}
                  >
                    3. 发送并标记解决
                  </Button>
                  <Button
                    loading={manualReply.isPending}
                    disabled={!manualReplyText.trim()}
                    onClick={() => manualReply.mutate(false)}
                  >
                    仅发送，不关闭
                  </Button>
                  {String(viewMode) !== "guide" && (
                    <Button
                      loading={assignment.isPending}
                      onClick={() => assignment.mutate("release")}
                    >
                      释放会话
                    </Button>
                  )}
                </Space>
              </Space>
            ) : (
              <Space
                direction="vertical"
                size="middle"
                style={{ width: "100%", marginTop: 12 }}
              >
                <Text type="secondary">
                  AI 已自动准备回复草稿；接管会话后即可修改和发送。
                </Text>
                {replySuggestion.isPending && (
                  <Alert
                    type="info"
                    showIcon
                    message="AI 正在自动生成回复草稿…"
                  />
                )}
                {replySuggestion.data && (
                  <Alert
                    type="success"
                    showIcon
                    message="AI 已预生成回复草稿"
                    description={replySuggestion.data.text}
                  />
                )}
                {autoSuggestionError && !replySuggestion.isPending && (
                  <Alert
                    type="warning"
                    showIcon
                    message="AI 草稿生成失败"
                    description={autoSuggestionError}
                  />
                )}
                <Space wrap>
                  <Button
                    type="primary"
                    loading={assignment.isPending}
                    disabled={
                      !currentAgentId ||
                      assignedToAnotherAgent ||
                      cannotTakeOver
                    }
                    onClick={() => assignment.mutate("takeover")}
                  >
                    {capacityReached
                      ? `已达 ${currentAgentCapacity} 个会话上限`
                      : "接管并开始处理"}
                  </Button>
                  <Text type="secondary">
                    当前负责 {currentAgentLoad} / {currentAgentCapacity} 个活动会话
                  </Text>
                </Space>
                {capacityReached && (
                  <Alert
                    type="warning"
                    showIcon
                    message="当前客服已满载"
                    description="请先打开一个由自己负责的会话并点击“释放会话”，再接管新会话。"
                  />
                )}
              </Space>
            )}
          </Card>

          {String(viewMode) !== "guide" && (
          <Card size="small" title="物流查询" style={{ marginTop: 16 }}>
            <Space
              direction="vertical"
              size="middle"
              style={{ width: "100%" }}
            >
              <Alert
                type={logisticsConfigured ? "success" : "warning"}
                showIcon
                message={
                  logisticsConfigured
                    ? "已配置真实物流查询接口"
                    : "物流查询接口尚未配置"
                }
                description={
                  logisticsConfigured
                    ? "查询结果来自企业订单或物流服务，不会由模型猜测。"
                    : "请先取得订单号或运单号，并配置企业 OMS、WMS 或快递查询接口。系统当前不会生成虚假物流状态。"
                }
              />
              <Input
                value={logisticsOrderId}
                onChange={(event) => setLogisticsOrderId(event.target.value)}
                placeholder="订单号（可选，订单号和运单号至少填一个）"
                disabled={!logisticsConfigured}
              />
              <Input
                value={trackingNumber}
                onChange={(event) => setTrackingNumber(event.target.value)}
                placeholder="运单号，例如 SF1234567890"
                disabled={!logisticsConfigured}
              />
              <Input
                value={carrierCode}
                onChange={(event) => setCarrierCode(event.target.value)}
                placeholder="快递公司编码（可选），例如 SF、YTO、ZTO"
                disabled={!logisticsConfigured}
              />
              <Button
                loading={logistics.isPending}
                disabled={
                  !logisticsConfigured ||
                  (!logisticsOrderId.trim() && !trackingNumber.trim())
                }
                onClick={() => logistics.mutate()}
              >
                查询真实物流状态
              </Button>
              {logistics.data && (
                <Card size="small" title="最新物流状态">
                  <Descriptions column={2} size="small" bordered>
                    <Descriptions.Item label="状态">
                      <Tag color="blue">{logistics.data.status_label}</Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="运单号">
                      {logistics.data.tracking_number ?? "-"}
                    </Descriptions.Item>
                    <Descriptions.Item label="快递公司">
                      {logistics.data.carrier_code ?? "-"}
                    </Descriptions.Item>
                    <Descriptions.Item label="更新时间">
                      {logistics.data.latest_event_at
                        ? new Date(
                            logistics.data.latest_event_at,
                          ).toLocaleString()
                        : "-"}
                    </Descriptions.Item>
                  </Descriptions>
                  {logistics.data.events.length > 0 ? (
                    <Timeline
                      style={{ marginTop: 16 }}
                      items={logistics.data.events.map((event) => ({
                        color: "blue",
                        children: (
                          <Space direction="vertical" size={0}>
                            <Text strong>{event.description}</Text>
                            <Text type="secondary">
                              {event.location ?? "位置未知"} ·{" "}
                              {event.occurred_at
                                ? new Date(event.occurred_at).toLocaleString()
                                : "时间未知"}
                            </Text>
                          </Space>
                        ),
                      }))}
                    />
                  ) : (
                    <Text type="secondary">物流服务暂未返回轨迹明细。</Text>
                  )}
                </Card>
              )}
            </Space>
          </Card>
          )}

          <Timeline
            style={{ marginTop: 24 }}
            items={[
              { color: "blue", children: "买家已提交问题" },
              {
                color: "blue",
                children: ticket.classification
                  ? `分类完成：${
                      categoryLabels[ticket.classification.primary] ??
                      ticket.classification.primary
                    }`
                  : "正在分类",
              },
              {
                color: ticket.draft ? "green" : ticket.needs_human ? "orange" : "gray",
                children: ticket.draft
                  ? `回答草稿已生成 · ${localizedLabel(
                      groundingStatusLabels,
                      ticket.draft.grounding_status,
                    )}`
                  : ticket.needs_human
                    ? `已转人工：${localizedLabel(
                        humanReasonLabels,
                        ticket.routing.human_reason,
                        "需要人工处理",
                      )}`
                    : "正在检索知识",
              },
            ]}
          />

          {ticket.routing.human_reason === "KNOWLEDGE_NOT_FOUND" && (
            <Alert
              type="warning"
              showIcon
              message="知识库没有命中相关内容"
              description="系统已阻止无依据回答，并自动生成知识缺失修复任务。"
            />
          )}

          {ticket.draft && (
            <Card size="small" title="数字员工回答" style={{ marginTop: 16 }}>
              <Paragraph>{ticket.draft.text}</Paragraph>
              <Space wrap>
                <Tag>{localizedLabel(draftStateLabels, ticket.draft.status)}</Tag>
                <Tag>
                  {localizedLabel(
                    providerLabels,
                    ticket.draft.generator_provider,
                    "回答模型",
                  )}
                </Tag>
                <Tag color={ticket.draft.grounding_status === "GROUNDED" ? "green" : "gold"}>
                  {localizedLabel(
                    groundingStatusLabels,
                    ticket.draft.grounding_status,
                  )}
                </Tag>
              </Space>
              {ticket.draft.citations.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <Text strong>知识引用</Text>
                  {ticket.draft.citations.map((citation, index) => (
                    <Paragraph key={`${citation.document_id}-${index}`}>
                      {citation.title} · v{citation.version}
                    </Paragraph>
                  ))}
                </div>
              )}
              {pendingReview && (
                <Space direction="vertical" size="middle" style={{ width: "100%", marginTop: 16 }}>
                  <TextArea
                    rows={4}
                    value={editedText}
                    onChange={(event) => setEditedText(event.target.value)}
                  />
                  <Space wrap>
                    <Button
                      onClick={() =>
                        review.mutate({ decision: "ACCEPTED" })
                      }
                    >
                      直接采纳
                    </Button>
                    <Button
                      type="primary"
                      disabled={!editedText.trim() || editedText === ticket.draft.text}
                      onClick={() =>
                        review.mutate({
                          decision: "EDITED_AND_ACCEPTED",
                          text: editedText,
                        })
                      }
                    >
                      保存人工改写
                    </Button>
                    <Button onClick={() => feedback.mutate("POSITIVE")}>有用</Button>
                    <Button danger onClick={() => feedback.mutate("NEGATIVE")}>点踩</Button>
                  </Space>
                </Space>
              )}
            </Card>
          )}
          </Card>
        </div>
      )}
      <Modal
        open={Boolean(assignmentResult)}
        title="主管补派结果"
        footer={
          <Button onClick={() => setAssignmentResult(null)}>知道了</Button>
        }
        onCancel={() => setAssignmentResult(null)}
        width={760}
      >
        {assignmentResult && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message="人工客服自动分配不是按关键词随意分人"
              description="系统会先按客服技能和高风险权限筛选，再比较当前会话负载。后台每 10 秒自动执行；这里的手动补派用于立即处理或验证。"
            />
            <Space wrap>
              <Tag color="green">
                本次分配 {assignmentResult.assigned_count}
              </Tag>
              <Tag color="gold">
                仍待处理 {assignmentResult.unassigned_count}
              </Tag>
            </Space>
            {assignmentResult.assignments.length === 0 ? (
              <Alert
                type="warning"
                showIcon
                message="本次没有可分配会话"
                description="请检查客服是否在线、是否开启自动接单、技能和风险权限是否覆盖，以及当前并发是否已满。"
              />
            ) : (
              assignmentResult.assignments.map((assignment) => (
                <Card
                  key={assignment.conversation_id}
                  size="small"
                  title={`会话 ${assignment.conversation_id.slice(0, 8)}`}
                  extra={<Tag>{assignment.priority}</Tag>}
                >
                  <Space
                    direction="vertical"
                    size="small"
                    style={{ width: "100%" }}
                  >
                    <Text strong>分配给：{assignment.agent_id}</Text>
                    <Text type="secondary">{assignment.reason}</Text>
                    <Collapse
                      size="small"
                      items={[
                        {
                          key: "candidates",
                          label: `查看 ${assignment.candidates.length} 位候选人的筛选依据`,
                          children: (
                            <Table
                              rowKey="agent_id"
                              size="small"
                              pagination={{ pageSize: 10, showSizeChanger: true }}
                              dataSource={assignment.candidates}
                              scroll={{ x: 620 }}
                              columns={[
                                {
                                  title: "人工客服",
                                  dataIndex: "agent_id",
                                  render: (value: string, candidate) => (
                                    <Space size={4}>
                                      <Text strong>{value}</Text>
                                      {candidate.selected && (
                                        <Tag color="green">已选中</Tag>
                                      )}
                                    </Space>
                                  ),
                                },
                                {
                                  title: "筛选结果",
                                  render: (_value, candidate) =>
                                    candidate.eligible ? (
                                      <Tag color="green">可接单</Tag>
                                    ) : (
                                      <Space wrap size={4}>
                                        {candidate.excluded_reasons.map(
                                          (reason) => (
                                            <Tag color="red" key={reason}>
                                              {reason}
                                            </Tag>
                                          ),
                                        )}
                                      </Space>
                                    ),
                                },
                                {
                                  title: "负载",
                                  render: (_value, candidate) =>
                                    `${candidate.load}/${candidate.max_conversations}`,
                                },
                                {
                                  title: "风险权限",
                                  dataIndex: "risk_clearance",
                                },
                                {
                                  title: "技能",
                                  dataIndex: "skills",
                                  render: (value: string[]) =>
                                    value.join("、") || "未限定",
                                },
                              ]}
                            />
                          ),
                        },
                      ]}
                    />
                  </Space>
                </Card>
              ))
            )}
          </Space>
        )}
      </Modal>
      <Modal
        open={Boolean(approvalDecision)}
        title={
          approvalDecision?.decision === "APPROVE"
            ? "审批并执行 MCP 写操作"
            : "拒绝 MCP 写操作"
        }
        okText={
          approvalDecision?.decision === "APPROVE"
            ? "确认审批并执行"
            : "确认拒绝"
        }
        okButtonProps={{
          danger: approvalDecision?.decision === "APPROVE",
          loading: decideApproval.isPending,
        }}
        onOk={() => {
          if (approvalDecision) decideApproval.mutate(approvalDecision);
        }}
        onCancel={() => {
          setApprovalDecision(null);
          setApprovalNote("");
        }}
      >
        {approvalDecision && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type={
                approvalDecision.decision === "APPROVE" ? "warning" : "info"
              }
              showIcon
              message={approvalDecision.approval.tool_id}
              description={
                approvalDecision.decision === "APPROVE"
                  ? "确认后将立即调用外部 MCP 写工具，只执行一次。请核对订单、金额和业务条件。"
                  : "拒绝后不会调用外部写工具。之后如需重新申请，应由业务会话重新发起。"
              }
            />
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="申请人">
                {approvalDecision.approval.requested_by}
              </Descriptions.Item>
              <Descriptions.Item label="工具参数">
                <Text code>
                  {JSON.stringify(approvalDecision.approval.arguments)}
                </Text>
              </Descriptions.Item>
              <Descriptions.Item label="申请原因">
                {approvalDecision.approval.reason || "未提供"}
              </Descriptions.Item>
              <Descriptions.Item label="审批等级">
                {approvalDecision.approval.required_role === "admin"
                  ? "管理员"
                  : "主管或管理员"}
              </Descriptions.Item>
            </Descriptions>
            <TextArea
              rows={3}
              value={approvalNote}
              onChange={(event) => setApprovalNote(event.target.value)}
              placeholder="填写审批意见或拒绝理由"
            />
            <Text type="secondary">
              当前审批身份：页面右上角选择的测试身份或 OIDC 登录身份
            </Text>
          </Space>
        )}
      </Modal>
      <Modal
        open={Boolean(incidentDecision)}
        title={
          incidentDecision?.action === "acknowledge"
            ? "确认处理执行异常"
            : "关闭执行异常"
        }
        okText={
          incidentDecision?.action === "acknowledge"
            ? "确认接手"
            : "确认关闭"
        }
        okButtonProps={{
          loading: updateIncident.isPending,
          disabled:
            incidentDecision?.action === "resolve" &&
            !incidentNote.trim(),
        }}
        onOk={() => {
          if (incidentDecision) updateIncident.mutate(incidentDecision);
        }}
        onCancel={() => {
          setIncidentDecision(null);
          setIncidentNote("");
        }}
      >
        {incidentDecision && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type="warning"
              showIcon
              message={incidentDecision.incident.tool_id}
              description={incidentDecision.incident.required_action}
            />
            {incidentDecision.action === "resolve" && (
              <Select
                value={incidentOutcome}
                onChange={setIncidentOutcome}
                options={[
                  {
                    value: "NOT_EXECUTED",
                    label: "核对确认未执行",
                  },
                  {
                    value: "EXECUTED_AS_INTENDED",
                    label: "已执行且结果正确",
                  },
                  {
                    value: "EXECUTED_INCORRECTLY",
                    label: "已执行但结果错误（需补偿）",
                  },
                  {
                    value: "INCONCLUSIVE",
                    label: "仍无法判断",
                  },
                ]}
              />
            )}
            <TextArea
              rows={4}
              value={incidentNote}
              onChange={(event) => setIncidentNote(event.target.value)}
              placeholder={
                incidentDecision.action === "resolve"
                  ? "必填：记录在哪个系统核对了什么结果，以及是否确认未执行或已执行"
                  : "记录接手说明或待核查事项"
              }
            />
          </Space>
        )}
      </Modal>
      <Modal
        open={Boolean(compensationIncident)}
        title="提交 MCP 补偿审批"
        okText="创建补偿审批"
        okButtonProps={{
          danger: true,
          loading: requestCompensation.isPending,
          disabled: !compensationNote.trim(),
        }}
        onOk={() => {
          if (compensationIncident) {
            requestCompensation.mutate(compensationIncident);
          }
        }}
        onCancel={() => setCompensationIncident(null)}
      >
        {compensationIncident && (
          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
            <Alert
              type="error"
              showIcon
              message="补偿会创建新的管理员审批单"
              description="补偿工具不会自动执行。新审批必须由另一名管理员批准，执行成功后才允许把原事故标记为“执行结果错误”并关闭。"
            />
            <Input
              value={compensationToolId}
              onChange={(event) =>
                setCompensationToolId(event.target.value)
              }
              placeholder="补偿工具 ID；留空则使用 reverse/compensate 工具"
            />
            <TextArea
              rows={5}
              value={compensationArguments}
              onChange={(event) =>
                setCompensationArguments(event.target.value)
              }
              placeholder='补偿参数 JSON，例如 {"order_id":"...","amount":59.9}'
            />
            <TextArea
              rows={3}
              value={compensationNote}
              onChange={(event) => setCompensationNote(event.target.value)}
              placeholder="必填：说明为什么需要补偿及核对依据"
            />
          </Space>
        )}
      </Modal>
    </Space>
  );
}
