import {
  Alert,
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
  Space,
  Statistic,
  Steps,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  heartbeatCustomerAgent,
  watchCustomerConversation,
} from "./api";
import type {
  AssignmentRunResult,
  McpActionIncident,
  McpToolApproval,
} from "./types";
import { message } from "./feedback";
import { useAuth } from "./auth";
import {
  conversationStatusLabels,
  draftStateLabels,
  gateDecisionLabels,
  gateReasonLabel,
  groundingStatusLabels,
  humanReasonLabels,
  localizedLabel,
  providerLabels,
  queueLabels,
  workflowStateLabels,
} from "./statusLabels";
import CustomerServiceWorkbench from "./CustomerServiceWorkbench";

import { CustomerChatDemo } from "./features/customer-service/CustomerChatDemo";
import {
  approvalStatusColor,
  approvalStatusLabels,
  categoryLabels,
  compensationStatusLabels,
  incidentFailureLabels,
  incidentStatusLabels,
  loadSandboxState,
  reconciliationStatusLabels,
  riskColor,
  riskLevels,
  sandboxStorageKey,
  ticketOutcome,
  workflowColor,
  type ConversationFilter,
  type CustomerServiceSection,
  type CustomerServiceSurfaceMode,
  type HistoryScope,
  type StoredSandboxState,
} from "./features/customer-service/model";
import { useApprovalMutations } from "./features/customer-service/useApprovalMutations";
import { useConversationHistory } from "./features/customer-service/useConversationHistory";
import { useCustomerServiceView } from "./features/customer-service/useCustomerServiceView";
import { useCustomerServiceQueries } from "./features/customer-service/useCustomerServiceQueries";
import { useReplyMutations } from "./features/customer-service/useReplyMutations";
import { useTicketMutations } from "./features/customer-service/useTicketMutations";

export type { CustomerServiceSection };

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

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
  const { hasCapability } = useAuth();
  const [stored] = useState(loadSandboxState);
  const canOpenAdmin = hasCapability("service.admin");
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
  const {
    historyScope,
    setHistoryScope,
    followLatest,
    setFollowLatest,
    historyContainerRef,
    scrollToTicketOnLoad,
    setScrollToTicketOnLoad,
    history,
    setHistory,
  } = useConversationHistory({
    initialHistory: stored?.history ?? [],
  });
  const conversationListRef = useRef<HTMLDivElement>(null);
  const ticketPanelRef = useRef<HTMLDivElement>(null);
  const [logisticsOrderId, setLogisticsOrderId] = useState("");
  const [trackingNumber, setTrackingNumber] = useState("");
  const [carrierCode, setCarrierCode] = useState("");
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
  const { demoScenario, viewMode, setViewMode } = useCustomerServiceView({
    technicalMode,
    section,
  });

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

  const isAdminSurface = viewMode === "admin" && canOpenAdmin;
  const canViewApprovals = hasCapability("service.approvals.view");
  const canDecideApprovals = hasCapability("service.approvals.decide");
  const canViewIncidents = hasCapability("service.incidents.view");
  const canManageIncidents = hasCapability("service.incidents.manage");

  const {
    employees,
    categories,
    products,
    spaces,
    conversations,
    presence,
    assignmentQueue,
    serviceAlerts,
    notifications,
    mcpApprovals,
    mcpIncidents,
    metrics,
    historyMetrics,
    runtime,
    detail,
    conversationDetail,
    knowledgeBindings,
  } = useCustomerServiceQueries({
    isAdminSurface,
    section,
    approvalFilter,
    incidentFilter,
    ticketId,
    conversationId,
    employeeId,
    canViewApprovals,
    canViewIncidents,
    canViewEmployeeDirectory: hasCapability("employees.directory"),
  });

  const currentAgentCapacity =
    presence.data?.items.find(
      (agent) => agent.agent_id === currentAgentId,
    )?.max_conversations ?? 5;

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
  }, [conversationId, setFollowLatest, setHistoryScope]);

  useEffect(() => {
    const currentTicketId = conversationDetail.data?.current_ticket_id;
    if (currentTicketId) setTicketId(currentTicketId);
    const conversationEmployeeId = conversationDetail.data?.employee_id;
    if (conversationEmployeeId) setEmployeeId(conversationEmployeeId);
    const conversationCategoryId =
      conversationDetail.data?.category_profile_id;
    if (conversationCategoryId) setCategoryProfileId(conversationCategoryId);
  }, [conversationDetail.data]);

  const {
    createTicket,
    review,
    feedback,
    assignment,
    autoAssign,
    acknowledgeNotification,
  } = useTicketMutations({
    conversationId,
    conversationDetail: conversationDetail.data,
    employeeId,
    demoScenario,
    categoryProfileId,
    categoryProfileName: categories.data?.find(
      (item) => item.id === categoryProfileId,
    )?.name,
    productId,
    categoryProducts,
    ticketId,
    ticketDetail: detail.data,
    feedbackSpace,
    currentAgentCapacity,
    onConversationCreated: (conversation, input) => {
      setHistory((current) =>
        input.newConversation
          ? [{ role: "BUYER", text: input.body }]
          : [...current, { role: "BUYER", text: input.body }],
      );
      setConversationId(conversation.id);
      setTicketId(conversation.current_ticket_id ?? "");
      setScrollToTicketOnLoad(true);
    },
    onReviewAnswer: (answer) => {
      setHistory((current) => [
        ...current,
        { role: "ASSISTANT", text: answer },
      ]);
    },
    onAssignmentResult: (result) => setAssignmentResult(result),
    onTakeOver: () => {
      window.setTimeout(() => {
        ticketPanelRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }, 150);
    },
  });
  const {
    decideApproval,
    updateIncident,
    reconcileIncident,
    requestCompensation,
  } = useApprovalMutations({
    approvalNote,
    incidentNote,
    incidentOutcome,
    compensationToolId,
    compensationArguments,
    compensationNote,
    onApprovalDecisionHandled: () => {
      setApprovalDecision(null);
      setApprovalNote("");
    },
    onIncidentActionHandled: () => {
      setIncidentDecision(null);
      setIncidentNote("");
    },
    onCompensationRequested: () => {
      setCompensationIncident(null);
      setCompensationToolId("");
      setCompensationArguments("{}");
      setCompensationNote("");
    },
  });
  const {
    manualReply,
    logistics,
    replySuggestion,
    optimizeReply,
  } = useReplyMutations({
    conversationId,
    conversationAssignedAgentId: conversationDetail.data?.assigned_agent_id,
    currentAgentId,
    manualReplyText,
    ticketId,
    logisticsOrderId,
    trackingNumber,
    carrierCode,
    optimizationStyle,
    onManualReplySent: () => setManualReplyText(""),
    onSuggestionLoaded: (text) => {
      setManualReplyText(text);
      setAutoSuggestionError("");
    },
    onSuggestionFailed: (errorMessage) => setAutoSuggestionError(errorMessage),
    onReplyOptimized: (text) => setManualReplyText(text),
  });

  const ticket = detail.data;
  const pendingReview = ticket?.workflow_state === "PENDING_REVIEW";
  const conversationItems = useMemo(
    () => conversations.data?.items ?? [],
    [conversations.data?.items],
  );
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
    historyContainerRef,
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
  }, [conversationId, scrollToTicketOnLoad, ticket, setScrollToTicketOnLoad]);

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
      {metrics.isError && (
        <Alert
          type="error"
          showIcon
          message="运营指标加载失败"
          description="当前无法确认会话负载和 SLA 状态，指标不会以 0 代替。请检查权限或后端服务。"
        />
      )}
      <Row gutter={[12, 12]}>
        {[
          ["活动会话", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.active_conversations ?? 0],
          ["待接管", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.unassigned_conversations ?? 0],
          ["在线客服", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.online_agents ?? 0],
          ["SLA 超时", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.sla_overdue ?? 0],
          ["主管告警", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.open_supervisor_notifications ?? 0],
          [
            "平均等待",
            metrics.isError
              ? "-"
              : metrics.isLoading
                ? "…"
                : `${Math.floor((metrics.data?.average_waiting_seconds ?? 0) / 60)} 分钟`,
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
            待评估{" "}
            {metrics.isError
              ? "-"
              : metrics.isLoading
                ? "…"
                : metrics.data?.risk_counts?.UNKNOWN ?? 0}{" "}
            · 风险决定授权边界，优先级决定处理时效
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
                    {metrics.isError
                      ? "-"
                      : metrics.isLoading
                        ? "…"
                        : metrics.data?.risk_counts?.[level.code] ?? 0}
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
        {historyMetrics.isError && (
          <Alert
            type="error"
            showIcon
            message="近 7 天趋势加载失败"
            description="趋势数据不可用，不代表新增会话或首响时间为 0。"
            style={{ marginBottom: 12 }}
          />
        )}
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
                  canDecideApprovals ? (
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
                    <Text type="secondary">等待有权限的审批人处理</Text>
                  )
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
                  canManageIncidents ? (
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
                    <Text type="secondary">只读查看，处理需主管权限</Text>
                  )
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
                        {replySuggestion.data.gate && (
                          <Text
                            type={
                              replySuggestion.data.gate.decision === "AUTO_SEND"
                                ? "success"
                                : "warning"
                            }
                          >
                            发送门禁：
                            {localizedLabel(
                              gateDecisionLabels,
                              replySuggestion.data.gate.decision,
                              replySuggestion.data.gate.decision,
                            )}
                            {replySuggestion.data.gate.reasons.length > 0
                              ? `（${replySuggestion.data.gate.reasons
                                  .map(gateReasonLabel)
                                  .join("；")}）`
                              : "（证据与 Skill 校验均通过）"}
                          </Text>
                        )}
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
