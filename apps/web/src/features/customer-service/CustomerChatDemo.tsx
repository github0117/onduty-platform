import {
  Alert,
  Avatar,
  Button,
  Card,
  Collapse,
  Descriptions,
  Input,
  Select,
  Skeleton,
  Space,
  Steps,
  Tabs,
  Tag,
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
  createCustomerConversation,
  generateCustomerReplySuggestion,
  getCustomerConversation,
  getTicket,
  listBusinessServiceEntries,
  listDigitalEmployeeRouteDecisions,
  listDigitalEmployees,
  listEcommerceCategoryProfiles,
  listEcommerceProducts,
  reviewTicket,
  streamCustomerConversationMessage,
  switchCustomerConversationEmployee,
  watchCustomerConversation,
} from "../../api";
import EmployeeProfileDrawer from "../../EmployeeProfileDrawer";
import type {
  CustomerConversation,
  CustomerReplySuggestion,
} from "../../types";
import { message } from "../../feedback";
import { useAuth } from "../../auth";
import {
  draftStateLabels,
  groundingStatusLabels,
  localizedLabel,
  workflowStateLabels,
} from "../../statusLabels";
import {
  REROUTE_REASON_LABELS,
  categoryLabels,
  getChatDemoStorageKey,
  handoffHeadline,
  loadChatDemoState,
  riskColor,
  type CustomerDemoScenario,
} from "./model";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;
const terminalStates = new Set(["COMPLETED", "FAILED_TERMINAL"]);

export function CustomerChatDemo({
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
  const { me, testIdentity, hasCapability } = useAuth();
  const actorKey = testIdentity?.id ?? me.actor_id;
  const chatStateStorageKey = getChatDemoStorageKey(scenario, actorKey);
  const requestedConversationId =
    new URLSearchParams(window.location.search).get("conversation") ?? "";
  const [stored] = useState(() => loadChatDemoState(scenario, actorKey));
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
  const [switchEmployeeId, setSwitchEmployeeId] = useState("");
  const [switchReason, setSwitchReason] = useState("");
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
    // 员工目录对坐席、主管、知识运营和管理员开放，用于显示本次接待员工；
    // 员工管理入口仍由 employees.view 单独控制。
    enabled: hasCapability("employees.directory"),
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
      ["PENDING", "RECEIVED", "RUNNING"].includes(currentTurn.status),
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
  const switchEmployee = useMutation({
    mutationFn: ({
      employeeId,
      reason,
    }: {
      employeeId: string;
      reason: string;
    }) => {
      if (!conversationId) throw new Error("当前还没有对话");
      return switchCustomerConversationEmployee(
        conversationId,
        employeeId,
        reason.trim(),
      );
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ["chat-demo-conversation", conversationId],
        updated,
      );
      setSwitchEmployeeId("");
      setSwitchReason("");
      void queryClient.invalidateQueries({
        queryKey: ["chat-demo-conversation", conversationId],
      });
      message.success(
        updated.latest_handoff?.to_employee_name
          ? `已交接给${updated.latest_handoff.to_employee_name}`
          : "已完成数字员工交接",
      );
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
              {hasCapability("operations.manage") &&
                conversationId &&
                employees.data?.length ? (
                <>
                  {/* Direct children of the wrapping row: on a narrow window
                      they move to the next line instead of being clipped. */}
                  <Select
                    size="small"
                    placeholder="切换到数字员工"
                    style={{ width: 140 }}
                    value={switchEmployeeId || undefined}
                    loading={employees.isLoading}
                    onChange={(value: string) => setSwitchEmployeeId(value)}
                    options={employees.data
                      .filter(
                        (employee) =>
                          employee.status === "ACTIVE" &&
                          // A customer conversation can only move to another
                          // customer service employee; the switch API refuses
                          // every other unit or domain.
                          employee.domain === "customer_service" &&
                          employee.id !== currentConversation?.employee_id,
                      )
                      .map((employee) => ({
                        value: employee.id,
                        label: employee.name,
                      }))}
                  />
                  <Input
                    size="small"
                    placeholder="交接原因（可选）"
                    style={{ width: 132 }}
                    value={switchReason}
                    maxLength={200}
                    onChange={(event) => setSwitchReason(event.target.value)}
                  />
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    loading={switchEmployee.isPending}
                    disabled={!switchEmployeeId}
                    onClick={() =>
                      switchEmployee.mutate({
                        employeeId: switchEmployeeId,
                        reason: switchReason,
                      })
                    }
                  >
                    交接
                  </Button>
                </>
              ) : null}
            </Space>
          </div>

          {currentConversation?.latest_handoff && (
            <Alert
              type="info"
              showIcon
              style={{ margin: "0 16px 8px" }}
              message={handoffHeadline(currentConversation.latest_handoff)}
              description={
                [
                  REROUTE_REASON_LABELS[
                    currentConversation.latest_handoff.reason_code
                  ],
                  currentConversation.latest_handoff.summary
                    .operator_reason,
                  currentConversation.latest_handoff.summary.open_actions
                    ?.length
                    ? `未完成事项 ${currentConversation.latest_handoff.summary.open_actions.length} 项`
                    : "",
                  currentConversation.latest_handoff.summary
                    .pending_questions?.length
                    ? `待确认 ${currentConversation.latest_handoff.summary.pending_questions.length} 项`
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ") || "交接摘要已写入下一轮上下文"
              }
            />
          )}

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
