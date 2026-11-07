import {
  Alert,
  Button,
  Segmented,
  Space,
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
import CustomerServiceWorkbench from "./CustomerServiceWorkbench";

import { CustomerChatDemo } from "./features/customer-service/CustomerChatDemo";
import {
  loadSandboxState,
  sandboxStorageKey,
  type ConversationFilter,
  type CustomerServiceSection,
  type CustomerServiceSurfaceMode,
  type StoredSandboxState,
} from "./features/customer-service/model";
import { ApprovalDecisionModal } from "./features/customer-service/components/ApprovalDecisionModal";
import { ApprovalQueuePanel } from "./features/customer-service/components/ApprovalQueuePanel";
import { AssignmentQueuePanel } from "./features/customer-service/components/AssignmentQueuePanel";
import { AssignmentResultModal } from "./features/customer-service/components/AssignmentResultModal";
import { CompensationModal } from "./features/customer-service/components/CompensationModal";
import { ConversationHistoryPanel } from "./features/customer-service/components/ConversationHistoryPanel";
import { ConversationListPanel } from "./features/customer-service/components/ConversationListPanel";
import { GuideCustomTicketPanel } from "./features/customer-service/components/GuideCustomTicketPanel";
import {
  GuideWalkthroughPanel,
  type GuidedScenario,
} from "./features/customer-service/components/GuideWalkthroughPanel";
import { IncidentDecisionModal } from "./features/customer-service/components/IncidentDecisionModal";
import { IncidentPanel } from "./features/customer-service/components/IncidentPanel";
import { OperationalMetricsPanel } from "./features/customer-service/components/OperationalMetricsPanel";
import { ServiceTrendPanel } from "./features/customer-service/components/ServiceTrendPanel";
import { TicketWorkspacePanel } from "./features/customer-service/components/TicketWorkspacePanel";
import { useApprovalMutations } from "./features/customer-service/useApprovalMutations";
import { useConversationHistory } from "./features/customer-service/useConversationHistory";
import { useCustomerServiceView } from "./features/customer-service/useCustomerServiceView";
import { useCustomerServiceQueries } from "./features/customer-service/useCustomerServiceQueries";
import { useReplyMutations } from "./features/customer-service/useReplyMutations";
import { useTicketMutations } from "./features/customer-service/useTicketMutations";

export type { CustomerServiceSection };

const { Paragraph, Text, Title } = Typography;

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
  const runGuidedScenario = (scenario: GuidedScenario) => {
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
        <GuideWalkthroughPanel
          guidedStep={guidedStep}
          setViewMode={setViewMode}
          assignment={assignment}
          createTicket={createTicket}
          ticketPanelRef={ticketPanelRef}
          runGuidedScenario={runGuidedScenario}
        />
      )}

      {viewMode === "guide" && (
        <GuideCustomTicketPanel
          subject={subject}
          setSubject={setSubject}
          body={body}
          setBody={setBody}
          createTicket={createTicket}
          displayedMessages={displayedMessages}
        />
      )}

      {viewMode === "admin" && section === "admin" && (
        <OperationalMetricsPanel metrics={metrics} />
      )}

      {viewMode === "admin" && section === "admin" && (
        <ServiceTrendPanel historyMetrics={historyMetrics} />
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
        <ApprovalQueuePanel
          approvalFilter={approvalFilter}
          setApprovalFilter={setApprovalFilter}
          mcpApprovals={mcpApprovals}
          canDecideApprovals={canDecideApprovals}
          selectConversation={selectConversation}
          setApprovalNote={setApprovalNote}
          setApprovalDecision={setApprovalDecision}
        />
      )}

      {viewMode === "admin" && section === "incidents" && (
        <IncidentPanel
          incidentFilter={incidentFilter}
          setIncidentFilter={setIncidentFilter}
          mcpIncidents={mcpIncidents}
          canManageIncidents={canManageIncidents}
          reconcileIncident={reconcileIncident}
          selectConversation={selectConversation}
          setIncidentNote={setIncidentNote}
          setIncidentOutcome={setIncidentOutcome}
          setIncidentDecision={setIncidentDecision}
          setCompensationIncident={setCompensationIncident}
          setCompensationToolId={setCompensationToolId}
          setCompensationArguments={setCompensationArguments}
          setCompensationNote={setCompensationNote}
        />
      )}

      {section === "chat" &&
        viewMode === "admin" && (
        <ConversationListPanel
          conversationListRef={conversationListRef}
          presence={presence}
          conversations={conversations}
          conversationFilter={conversationFilter}
          setConversationFilter={setConversationFilter}
          conversationItems={conversationItems}
          filteredConversations={filteredConversations}
          currentAgentId={currentAgentId}
          conversationId={conversationId}
          selectConversation={selectConversation}
        />
      )}

      {section === "admin" && (
        <AssignmentQueuePanel
          assignmentQueue={assignmentQueue}
          autoAssign={autoAssign}
          conversationId={conversationId}
          selectConversation={selectConversation}
        />
      )}

      {(section === "chat" || viewMode === "guide") &&
        displayedMessages.length > 0 && (
        <ConversationHistoryPanel
          followLatest={followLatest}
          setFollowLatest={setFollowLatest}
          historyScope={historyScope}
          setHistoryScope={setHistoryScope}
          historyContainerRef={historyContainerRef}
          currentTicketMessageCount={currentTicketMessageCount}
          conversationMessages={conversationMessages}
          history={history}
          historyEntries={historyEntries}
          currentTicketId={currentTicketId}
        />
      )}

      {(section === "chat" || viewMode === "guide") && ticket && (
        <TicketWorkspacePanel
          ticket={ticket}
          conversationDetail={conversationDetail}
          viewMode={viewMode}
          ticketPanelRef={ticketPanelRef}
          conversationListRef={conversationListRef}
          manualStep={manualStep}
          ticketCompleted={ticketCompleted}
          assignedAgentId={assignedAgentId}
          currentAgentId={currentAgentId}
          assignment={assignment}
          replySuggestion={replySuggestion}
          autoSuggestionError={autoSuggestionError}
          setViewMode={setViewMode}
          optimizationStyle={optimizationStyle}
          setOptimizationStyle={setOptimizationStyle}
          optimizeReply={optimizeReply}
          manualReplyText={manualReplyText}
          setManualReplyText={setManualReplyText}
          manualReply={manualReply}
          capacityReached={capacityReached}
          currentAgentCapacity={currentAgentCapacity}
          currentAgentLoad={currentAgentLoad}
          cannotTakeOver={cannotTakeOver}
          assignedToAnotherAgent={assignedToAnotherAgent}
          logisticsConfigured={logisticsConfigured}
          logisticsOrderId={logisticsOrderId}
          setLogisticsOrderId={setLogisticsOrderId}
          trackingNumber={trackingNumber}
          setTrackingNumber={setTrackingNumber}
          carrierCode={carrierCode}
          setCarrierCode={setCarrierCode}
          logistics={logistics}
          pendingReview={pendingReview}
          editedText={editedText}
          setEditedText={setEditedText}
          review={review}
          feedback={feedback}
        />
      )}
      <AssignmentResultModal
        assignmentResult={assignmentResult}
        setAssignmentResult={setAssignmentResult}
      />
      <ApprovalDecisionModal
        approvalDecision={approvalDecision}
        decideApproval={decideApproval}
        approvalNote={approvalNote}
        setApprovalNote={setApprovalNote}
        setApprovalDecision={setApprovalDecision}
      />
      <IncidentDecisionModal
        incidentDecision={incidentDecision}
        updateIncident={updateIncident}
        incidentNote={incidentNote}
        setIncidentNote={setIncidentNote}
        incidentOutcome={incidentOutcome}
        setIncidentOutcome={setIncidentOutcome}
        setIncidentDecision={setIncidentDecision}
      />
      <CompensationModal
        compensationIncident={compensationIncident}
        setCompensationIncident={setCompensationIncident}
        requestCompensation={requestCompensation}
        compensationToolId={compensationToolId}
        setCompensationToolId={setCompensationToolId}
        compensationArguments={compensationArguments}
        setCompensationArguments={setCompensationArguments}
        compensationNote={compensationNote}
        setCompensationNote={setCompensationNote}
      />
    </Space>
  );
}
