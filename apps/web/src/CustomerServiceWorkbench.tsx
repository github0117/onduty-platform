import {
  Alert,
  Avatar,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Modal,
  Segmented,
  Select,
  Skeleton,
  Space,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  autoAssignCustomerConversations,
  generateCustomerReplySuggestion,
  getCustomerBusinessContext,
  getCustomerAssignmentQueue,
  getCustomerConversation,
  getCustomerServiceMetrics,
  getTicket,
  heartbeatCustomerAgent,
  listCustomerAgentPresence,
  listCustomerConversations,
  listCustomerServiceAlerts,
  optimizeCustomerReply,
  releaseCustomerConversation,
  requestCustomerAddressChange,
  reviewTicket,
  sendManualCustomerReply,
  takeOverCustomerConversation,
  watchCustomerConversation,
} from "./api";
import {
  conversationStatusLabels,
  draftStateLabels,
  gateDecisionLabels,
  gateReasonLabel,
  humanReasonLabels,
  localizedLabel,
  queueLabels,
  riskReasonLabels,
  ticketCategoryLabels,
  ticketSecondaryLabels,
  workflowStateLabels,
} from "./statusLabels";
import type {
  AccuracyGate,
  CustomerConversation,
  TicketDetail,
} from "./types";
import { message } from "./feedback";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

type WorkbenchFilter = "all" | "mine" | "waiting" | "review" | "completed";
type WorkbenchActionTab = "handle" | "review" | "info";

function statusColor(status: string | null | undefined): string {
  if (status === "COMPLETED") return "green";
  if (status === "NEEDS_HUMAN" || status === "FAILED_TERMINAL") return "red";
  if (status === "PENDING_REVIEW") return "gold";
  if (status === "TAKEN_OVER") return "purple";
  return "blue";
}

function riskColor(level: string | null | undefined): string {
  if (level === "R3") return "red";
  if (level === "R2") return "volcano";
  if (level === "R1") return "gold";
  if (level === "R0") return "green";
  return "default";
}

function draftStatusLabel(ticket: TicketDetail | undefined): string {
  if (!ticket?.draft) return "暂无草稿";
  return localizedLabel(draftStateLabels, ticket.draft.status);
}

export default function CustomerServiceWorkbench({
  technicalMode,
  initialConversationId = "",
  onOpenChat,
  onOpenAdmin,
  onOpenApprovals,
}: {
  technicalMode: boolean;
  initialConversationId?: string;
  onOpenChat: (conversationId?: string) => void;
  onOpenAdmin?: () => void;
  onOpenApprovals?: () => void;
}) {
  const queryClient = useQueryClient();
  const [selectedConversationId, setSelectedConversationId] =
    useState(initialConversationId);
  const [filter, setFilter] = useState<WorkbenchFilter>(
    initialConversationId ? "all" : "mine",
  );
  const [actionTab, setActionTab] =
    useState<WorkbenchActionTab>("handle");
  const [currentAgentId, setCurrentAgentId] = useState("");
  const [manualReplyText, setManualReplyText] = useState("");
  const [suggestionError, setSuggestionError] = useState("");
  const [suggestionStatus, setSuggestionStatus] = useState("");
  const [suggestionGate, setSuggestionGate] = useState<AccuracyGate | null>(
    null,
  );
  const [autoAssignStatus, setAutoAssignStatus] = useState("");
  const [editingReview, setEditingReview] = useState(false);
  const [reviewText, setReviewText] = useState("");
  const [optimizationStyle, setOptimizationStyle] = useState<
    "professional" | "concise" | "empathetic"
  >("professional");
  const [followLatest, setFollowLatest] = useState(true);
  const [pendingReplyText, setPendingReplyText] = useState("");
  const [addressModalOpen, setAddressModalOpen] = useState(false);
  const [addressActionError, setAddressActionError] = useState("");
  const [addressActionMessage, setAddressActionMessage] = useState("");
  const [addressApprovalId, setAddressApprovalId] = useState("");
  const [addressForm, setAddressForm] = useState({
    recipient: "",
    phone: "",
    province: "",
    city: "",
    district: "",
    detail: "",
    reason: "客户申请修改收货地址",
    simulationMode: "normal" as
      | "normal"
      | "timeout_unknown"
      | "reject",
  });
  const chatScrollRef = useRef<HTMLDivElement>(null);

  const conversations = useQuery({
    queryKey: ["workbench-conversations"],
    queryFn: listCustomerConversations,
    refetchInterval: 12_000,
    refetchIntervalInBackground: false,
  });
  const presence = useQuery({
    queryKey: ["workbench-presence"],
    queryFn: listCustomerAgentPresence,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  const queue = useQuery({
    queryKey: ["workbench-queue"],
    queryFn: getCustomerAssignmentQueue,
    refetchInterval: 12_000,
    refetchIntervalInBackground: false,
  });
  const alerts = useQuery({
    queryKey: ["workbench-alerts"],
    queryFn: listCustomerServiceAlerts,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  const metrics = useQuery({
    queryKey: ["workbench-metrics"],
    queryFn: getCustomerServiceMetrics,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });
  const conversation = useQuery({
    queryKey: ["workbench-conversation", selectedConversationId],
    queryFn: () => getCustomerConversation(selectedConversationId),
    enabled: Boolean(selectedConversationId),
    placeholderData: conversations.data?.items.find(
      (item) => item.id === selectedConversationId,
    ),
    refetchInterval: 12_000,
    refetchIntervalInBackground: false,
  });
  const currentTicketId = conversation.data?.current_ticket_id ?? "";
  const ticket = useQuery({
    queryKey: ["workbench-ticket", currentTicketId],
    queryFn: () => getTicket(currentTicketId),
    enabled: Boolean(currentTicketId),
    refetchInterval: (query) =>
      ["COMPLETED", "FAILED_TERMINAL"].includes(
        query.state.data?.workflow_state ?? "",
      )
        ? false
        : 2_000,
    refetchIntervalInBackground: false,
  });
  const businessContext = useQuery({
    queryKey: ["workbench-business-context", selectedConversationId],
    queryFn: () =>
      getCustomerBusinessContext(selectedConversationId),
    enabled: Boolean(selectedConversationId),
    retry: false,
    staleTime: 10_000,
  });

  useEffect(() => {
    const heartbeat = () => {
      heartbeatCustomerAgent(selectedConversationId || undefined)
        .then((item) => setCurrentAgentId(item.agent_id))
        .catch(() => undefined);
    };
    heartbeat();
    const timer = window.setInterval(heartbeat, 15_000);
    return () => window.clearInterval(timer);
  }, [selectedConversationId]);

  useEffect(() => {
    if (!selectedConversationId) return;
    const controller = new AbortController();
    watchCustomerConversation(
      selectedConversationId,
      (updated) => {
        queryClient.setQueryData(
          ["workbench-conversation", selectedConversationId],
          updated,
        );
      },
      controller.signal,
    ).catch(() => undefined);
    return () => controller.abort();
  }, [queryClient, selectedConversationId]);

  const conversationItems = conversations.data?.items ?? [];
  const filteredConversations = useMemo(() => {
    if (filter === "mine") {
      return conversationItems.filter(
        (item) =>
          Boolean(currentAgentId) &&
          item.assigned_agent_id === currentAgentId,
      );
    }
    if (filter === "waiting") {
      return conversationItems.filter(
        (item) => !item.assigned_agent_id && item.status === "ACTIVE",
      );
    }
    if (filter === "review") {
      return conversationItems.filter(
        (item) => item.current_workflow_state === "PENDING_REVIEW",
      );
    }
    if (filter === "completed") {
      return conversationItems.filter(
        (item) =>
          item.status === "COMPLETED" ||
          item.current_workflow_state === "COMPLETED",
      );
    }
    return conversationItems;
  }, [conversationItems, currentAgentId, filter]);

  useEffect(() => {
    if (
      selectedConversationId &&
      filteredConversations.some(
        (item) => item.id === selectedConversationId,
      )
    ) {
      return;
    }
    setSelectedConversationId(filteredConversations[0]?.id ?? "");
  }, [filteredConversations, selectedConversationId]);

  useEffect(() => {
    setManualReplyText("");
    setSuggestionError("");
    setSuggestionStatus("");
    setSuggestionGate(null);
    setEditingReview(false);
    setReviewText("");
    setPendingReplyText("");
    setFollowLatest(true);
    setAddressModalOpen(false);
    setAddressActionError("");
    setAddressActionMessage("");
    setAddressApprovalId("");
  }, [selectedConversationId]);

  const messages = conversation.data?.messages ?? [];
  const draftText = ticket.data?.draft?.text?.trim() ?? "";
  const latestAssistant = [...messages]
    .reverse()
    .find((item) => item.role === "ASSISTANT");
  const handedBackToAi = messages.some(
    (item) =>
      item.created_by === "digital_employee" &&
      item.content.includes("会话已交还数字员工"),
  );
  const draftAlreadyDelivered = Boolean(
    draftText &&
      latestAssistant &&
      latestAssistant.content.trim() === draftText,
  );
  const reviewRejected = ticket.data?.draft?.status === "REJECTED";
  useEffect(() => {
    if (!editingReview) {
      setReviewText(draftText);
    }
  }, [draftText, editingReview]);
  useEffect(() => {
    if (!followLatest) return;
    const frame = window.requestAnimationFrame(() => {
      const container = chatScrollRef.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages.length, selectedConversationId, followLatest, pendingReplyText]);

  const refreshConversation = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["workbench-conversations"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["workbench-conversation", selectedConversationId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["workbench-ticket", currentTicketId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["workbench-queue"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["workbench-presence"],
      }),
    ]);
  };

  const assignment = useMutation({
    mutationFn: (action: "takeover" | "release") => {
      if (!conversation.data) {
        throw new Error("请先选择会话");
      }
      return action === "takeover"
        ? takeOverCustomerConversation(
            conversation.data.id,
            conversation.data.version,
          )
        : releaseCustomerConversation(conversation.data.id);
    },
    onMutate: async (action) => {
      await Promise.all([
        queryClient.cancelQueries({
          queryKey: ["workbench-conversation", selectedConversationId],
        }),
        queryClient.cancelQueries({ queryKey: ["workbench-conversations"] }),
      ]);
      const previousConversation =
        queryClient.getQueryData<CustomerConversation>([
          "workbench-conversation",
          selectedConversationId,
        ]);
      if (!currentAgentId || !previousConversation) {
        return { previousConversation: undefined };
      }
      queryClient.setQueryData<CustomerConversation>(
        ["workbench-conversation", selectedConversationId],
        {
          ...previousConversation,
          assigned_agent_id:
            action === "takeover" ? currentAgentId : null,
          assigned_at:
            action === "takeover" ? new Date().toISOString() : null,
        },
      );
      return { previousConversation };
    },
    onSuccess: (result, action) => {
      message.success(action === "takeover" ? "已接管会话" : "已释放会话");
      queryClient.setQueryData(
        ["workbench-conversation", selectedConversationId],
        result,
      );
      void refreshConversation();
    },
    onError: (error: Error, _action, context) => {
      if (context?.previousConversation) {
        queryClient.setQueryData(
          ["workbench-conversation", selectedConversationId],
          context.previousConversation,
        );
      }
      message.error(error.message);
    },
  });

  const autoAssign = useMutation({
    mutationFn: autoAssignCustomerConversations,
    onSuccess: (result) => {
      setAutoAssignStatus(
        `本次自动分配 ${result.assigned_count} 个会话，剩余 ${result.unassigned_count} 个待处理。`,
      );
      message.success(
        `已自动分配 ${result.assigned_count} 个，剩余 ${result.unassigned_count} 个`,
      );
      void refreshConversation();
    },
    onError: (error: Error) => {
      setAutoAssignStatus(`自动补派失败：${error.message}`);
      message.error(error.message);
    },
  });

  const suggestion = useMutation({
    mutationFn: () => {
      if (!conversation.data) throw new Error("请先选择会话");
      return generateCustomerReplySuggestion(conversation.data.id);
    },
    onSuccess: (result) => {
      setManualReplyText(result.text);
      setActionTab("handle");
      setSuggestionError("");
      setSuggestionGate(result.gate ?? null);
      setSuggestionStatus(
        `建议已填入中间回复框 · ${result.provider}/${result.model} · ${
          result.citations.length
        } 条知识引用`,
      );
      message.success(
        result.fallback_used
          ? "模型失败，已生成本地规则建议"
          : "AI 人工回复建议已生成",
      );
    },
    onError: (error: Error) => {
      setSuggestionStatus("");
      setSuggestionGate(null);
      setSuggestionError(
        error instanceof ApiError
          ? error.code === "KNOWLEDGE_NOT_FOUND"
            ? "当前会话没有检索到可支撑回复的企业知识，因此系统不会编造回复。请补充知识、选择有对应资料的会话，或直接手工回复。"
            : error.code === "CONVERSATION_ASSIGNED_TO_ANOTHER_AGENT"
              ? "该会话已由其他客服处理，不能生成回复建议。"
              : error.message
          : error.message,
      );
      message.error(error.message);
    },
  });

  const optimize = useMutation({
    mutationFn: () => {
      if (!conversation.data) throw new Error("请先选择会话");
      if (!manualReplyText.trim()) throw new Error("请先填写回复内容");
      return optimizeCustomerReply(
        conversation.data.id,
        manualReplyText.trim(),
        optimizationStyle,
      );
    },
    onSuccess: (result) => {
      setManualReplyText(result.text);
      message.success("AI 已优化回复，请核对后发送");
    },
    onError: (error: Error) => message.error(error.message),
  });

  const addressChange = useMutation({
    mutationFn: () => {
      if (!conversation.data) throw new Error("请先选择会话");
      if (!businessContext.data) {
        throw new Error("请先读取当前客户和订单上下文");
      }
      return requestCustomerAddressChange(conversation.data.id, {
        orderId: businessContext.data.order.order_id,
        expectedOrderVersion:
          businessContext.data.order.order_version,
        recipient: addressForm.recipient.trim(),
        phone: addressForm.phone.trim(),
        province: addressForm.province.trim(),
        city: addressForm.city.trim(),
        district: addressForm.district.trim(),
        detail: addressForm.detail.trim(),
        reason: addressForm.reason.trim(),
        simulationMode: addressForm.simulationMode,
      });
    },
    onSuccess: (result) => {
      setAddressActionError("");
      setAddressActionMessage(result.message);
      setAddressApprovalId(result.approval_id ?? "");
      setAddressModalOpen(false);
      message.success("改址申请已进入审批流程");
      void queryClient.invalidateQueries({
        queryKey: ["workbench-business-context", selectedConversationId],
      });
    },
    onError: (error: Error) => {
      setAddressActionError(error.message);
      message.error(error.message);
    },
  });

  const sendReply = useMutation({
    mutationFn: ({
      resolve,
      text,
    }: {
      resolve: boolean;
      text: string;
    }) => {
      if (!conversation.data) throw new Error("请先选择会话");
      if (!text.trim()) throw new Error("请输入回复内容");
      return sendManualCustomerReply(
        conversation.data.id,
        text.trim(),
        resolve,
      );
    },
    onMutate: ({ text }) => {
      setPendingReplyText(text);
      setManualReplyText("");
      setFollowLatest(true);
      return { text };
    },
    onSuccess: (result, { resolve }) => {
      queryClient.setQueryData(
        ["workbench-conversation", selectedConversationId],
        result,
      );
      setPendingReplyText("");
      if (resolve) {
        setFilter("all");
        message.success("回复已发送，会话已交还数字员工");
      } else {
        message.success("回复已发送");
      }
      void refreshConversation();
    },
    onError: (error: Error, _resolve, context) => {
      setPendingReplyText("");
      if (context?.text) {
        setManualReplyText(context.text);
      }
      message.error(error.message);
    },
  });

  const review = useMutation({
    mutationFn: (input: {
      decision: "ACCEPTED" | "EDITED_AND_ACCEPTED" | "REJECTED";
      text?: string;
    }) => {
      if (!ticket.data?.draft) throw new Error("当前没有待审核草稿");
      return reviewTicket(
        ticket.data.id,
        ticket.data.version,
        input.decision,
        input.text,
      );
    },
    onSuccess: (result, input) => {
      setEditingReview(false);
      queryClient.setQueryData(
        ["workbench-ticket", currentTicketId],
        result,
      );
      message.success(
        input.decision === "REJECTED"
          ? "草稿已退回并转入人工处理"
          : input.decision === "EDITED_AND_ACCEPTED"
            ? "修改后的回复已通过审核"
            : "草稿已通过审核并进入发送流程",
      );
      void refreshConversation();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const assignedAgentId = conversation.data?.assigned_agent_id;
  const assignedToMe = Boolean(
    currentAgentId && assignedAgentId === currentAgentId,
  );
  const currentAgentLoad = conversationItems.filter(
    (item) =>
      item.status === "ACTIVE" &&
      Boolean(currentAgentId) &&
      item.assigned_agent_id === currentAgentId,
  ).length;
  const currentAgentCapacity =
    presence.data?.items.find(
      (item) => item.agent_id === currentAgentId,
    )?.max_conversations ?? 5;
  const canTakeOver =
    Boolean(currentAgentId) &&
    !assignedAgentId &&
    currentAgentLoad < currentAgentCapacity;
  const currentConversation = conversation.data;
  const currentTicket = ticket.data;
  const currentBusinessContext = businessContext.data;
  const openAddressChangeModal = () => {
    if (!currentBusinessContext) {
      message.warning("请先等待客户和订单上下文加载完成");
      return;
    }
    const address = currentBusinessContext.order.shipping_address;
    setAddressForm({
      recipient: address.recipient,
      phone: "",
      province: address.province,
      city: address.city,
      district: address.district,
      detail: `${address.detail}（演示新地址）`,
      reason: "客户申请修改收货地址",
      simulationMode: "normal",
    });
    setAddressActionError("");
    setAddressActionMessage("");
    setAddressApprovalId("");
    setAddressModalOpen(true);
  };
  const selectWorkbenchConversation = (conversationId: string) => {
    setFollowLatest(true);
    setSelectedConversationId(conversationId);
    const url = new URL(window.location.href);
    if (conversationId) {
      url.searchParams.set("conversation", conversationId);
    } else {
      url.searchParams.delete("conversation");
    }
    window.history.replaceState({}, "", url);
  };
  const prefetchConversation = (conversationId: string) => {
    if (
      !conversationId ||
      conversationId === selectedConversationId ||
      queryClient.getQueryData([
        "workbench-conversation",
        conversationId,
      ])
    ) {
      return;
    }
    void queryClient.prefetchQuery({
      queryKey: ["workbench-conversation", conversationId],
      queryFn: () => getCustomerConversation(conversationId),
      staleTime: 15_000,
    });
  };

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <span className="eyebrow">
            {technicalMode
              ? "CUSTOMER SERVICE · OPERATIONS"
              : "CUSTOMER SERVICE · WORKBENCH"}
          </span>
          <Title level={2}>
            {technicalMode ? "客服运营技术工作台" : "人工客服工作台"}
          </Title>
          <Paragraph type="secondary">
            左侧选会话，中间看对话，右侧完成接管、回复和审核。
            审批、事故和系统治理收在管理员视图。
          </Paragraph>
        </div>
        <Space wrap>
          <Button
            onClick={() => onOpenChat(selectedConversationId || undefined)}
          >
            返回聊天演示
          </Button>
          <Button
            type="primary"
            loading={autoAssign.isPending}
            onClick={() => autoAssign.mutate()}
          >
            自动补派
          </Button>
          {onOpenAdmin && (
            <Button onClick={onOpenAdmin}>管理员视图</Button>
          )}
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        message="工作台只处理当前会话"
        description="自动补派会按客服技能、风险权限和负载分配会话。选中会话后，所有接管、回复和审核操作都固定在右侧，不需要上下寻找。"
      />
      {autoAssignStatus && (
        <Alert
          type={autoAssignStatus.startsWith("自动补派失败") ? "error" : "success"}
          showIcon
          closable
          onClose={() => setAutoAssignStatus("")}
          message="自动补派结果"
          description={autoAssignStatus}
        />
      )}

      <div className="workbench-metrics">
        {[
          ["活动会话", metrics.data?.active_conversations ?? 0],
          ["待接管", queue.data?.total ?? 0],
          ["待审核", conversations.data?.items.filter(
            (item) => item.current_workflow_state === "PENDING_REVIEW",
          ).length ?? 0],
          ["SLA 超时", alerts.data?.total ?? 0],
        ].map(([label, value]) => (
          <Card size="small" key={String(label)}>
            <Statistic title={label} value={value} />
          </Card>
        ))}
      </div>

      <div className="workbench-grid">
        <Card
          className="workbench-list"
          title="会话列表"
          extra={<Tag>{filteredConversations.length}</Tag>}
        >
          <Segmented
            size="small"
            block
            value={filter}
            onChange={(value) => setFilter(value as WorkbenchFilter)}
            options={[
              { label: "我的", value: "mine" },
              { label: "待分配", value: "waiting" },
              { label: "待审核", value: "review" },
              { label: "全部", value: "all" },
            ]}
          />
          <div className="workbench-conversation-list">
            {filteredConversations.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`workbench-conversation-item ${
                  item.id === selectedConversationId ? "active" : ""
                }`}
                onFocus={() => prefetchConversation(item.id)}
                onMouseEnter={() => prefetchConversation(item.id)}
                onClick={() => {
                  selectWorkbenchConversation(item.id);
                }}
              >
                <Space direction="vertical" size={5}>
                  <Space wrap size={4}>
                    <Tag color={statusColor(item.current_workflow_state)}>
                      {localizedLabel(
                        workflowStateLabels,
                        item.current_workflow_state,
                        "处理中",
                      )}
                    </Tag>
                    <Tag color={riskColor(item.current_risk_level)}>
                      {item.current_risk_level ?? "-"}
                    </Tag>
                  </Space>
                  <Text strong className="workbench-conversation-title">
                    {item.requester_ref}
                  </Text>
                  <Text type="secondary">
                    {item.assigned_agent_id
                      ? `负责人：${item.assigned_agent_id}`
                      : "尚未接管"}
                  </Text>
                </Space>
              </button>
            ))}
            {filteredConversations.length === 0 && (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="当前筛选下没有会话"
              >
                <Space direction="vertical">
                  {(queue.data?.total ?? 0) > 0 && (
                    <Button
                      type="primary"
                      onClick={() => setFilter("waiting")}
                    >
                      查看 {queue.data?.total} 个待接管会话
                    </Button>
                  )}
                  <Button
                    onClick={() =>
                      onOpenChat(selectedConversationId || undefined)
                    }
                  >
                    去聊天演示发起消息
                  </Button>
                </Space>
              </Empty>
            )}
          </div>
        </Card>

        <Card
          className="workbench-chat chat-window"
          styles={{ body: { padding: 0 } }}
        >
          <div className="chat-window-header">
            <Space size="middle">
              <Avatar className="chat-avatar">客</Avatar>
              <div>
                <Text strong>
                  {currentConversation?.requester_ref ?? "选择一条会话"}
                </Text>
                <div className="chat-window-subtitle">
                  {currentConversation
                    ? `会话 ${currentConversation.id.slice(0, 8)}`
                    : "从左侧选择会话开始处理"}
                </div>
              </div>
            </Space>
            <Space wrap size={4}>
              {currentConversation?.current_workflow_state && (
                <Tag
                  color={statusColor(
                    currentConversation.current_workflow_state,
                  )}
                >
                  {localizedLabel(
                    workflowStateLabels,
                    currentConversation.current_workflow_state,
                  )}
                </Tag>
              )}
              {assignedAgentId && <Tag>{assignedAgentId}</Tag>}
            </Space>
          </div>
          <div
            ref={chatScrollRef}
            className="chat-scroll workbench-chat-scroll"
            onScroll={(event) => {
              const container = event.currentTarget;
              const distanceToBottom =
                container.scrollHeight -
                container.scrollTop -
                container.clientHeight;
              setFollowLatest(distanceToBottom < 64);
            }}
          >
            {conversation.isLoading && (
              <div className="chat-loading-messages" aria-label="正在加载会话">
                <Skeleton active avatar paragraph={{ rows: 2 }} />
                <Skeleton active avatar paragraph={{ rows: 3 }} />
              </div>
            )}
            {!conversation.isLoading && messages.map((item) => {
              const buyer = item.role === "BUYER";
              const human =
                item.role === "ASSISTANT" &&
                item.created_by !== "digital_employee";
              return (
                <div
                  className={`chat-message-row ${
                    buyer ? "buyer" : "assistant"
                  }`}
                  key={item.id}
                >
                  {!buyer && (
                    <Avatar className="chat-small-avatar">
                      {human ? "人" : "AI"}
                    </Avatar>
                  )}
                  <div className="chat-message-content">
                    <div className={`chat-bubble ${human ? "human" : ""}`}>
                      {item.content}
                    </div>
                    <div className="chat-bubble-meta">
                      {buyer
                        ? "用户"
                        : human
                          ? `人工客服 · ${item.created_by}`
                          : "数字员工"}
                    </div>
                  </div>
                </div>
              );
            })}
            {pendingReplyText && (
              <div className="chat-message-row assistant">
                <Avatar className="chat-small-avatar">人</Avatar>
                <div className="chat-message-content">
                  <div className="chat-bubble human chat-pending-buyer">
                    {pendingReplyText}
                  </div>
                  <div className="chat-bubble-meta">
                    人工客服 · 发送中
                  </div>
                </div>
              </div>
            )}
            {draftText && !draftAlreadyDelivered && (
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
                        value={reviewText}
                        onChange={(event) =>
                          setReviewText(event.target.value)
                        }
                      />
                    ) : (
                      draftText
                    )}
                    {(ticket.data?.draft?.citations.length ?? 0) > 0 && (
                      <div className="chat-citations">
                        <Text type="secondary">知识依据：</Text>
                        {ticket.data?.draft?.citations.map((citation) => (
                          <Tag
                            key={`${citation.document_id}-${citation.version}`}
                          >
                            {citation.title}
                          </Tag>
                        ))}
                      </div>
                    )}
                    {ticket.data?.workflow_state === "PENDING_REVIEW" && (
                      <div className="chat-review-actions">
                        {editingReview ? (
                          <>
                            <Button
                              type="primary"
                              size="small"
                              loading={review.isPending}
                              disabled={!reviewText.trim()}
                              onClick={() =>
                                review.mutate({
                                  decision: "EDITED_AND_ACCEPTED",
                                  text: reviewText.trim(),
                                })
                              }
                            >
                              修改后发送
                            </Button>
                            <Button
                              size="small"
                              disabled={review.isPending}
                              onClick={() => {
                                setEditingReview(false);
                                setReviewText(draftText);
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
                              loading={review.isPending}
                              onClick={() =>
                                review.mutate({ decision: "ACCEPTED" })
                              }
                            >
                              通过并发送
                            </Button>
                            <Button
                              size="small"
                              disabled={review.isPending}
                              onClick={() => {
                                setEditingReview(true);
                                setReviewText(draftText);
                              }}
                            >
                              修改后发送
                            </Button>
                            <Button
                              danger
                              size="small"
                              loading={review.isPending}
                              onClick={() =>
                                review.mutate({ decision: "REJECTED" })
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
                      : "数字员工建议 · 审核在当前气泡内完成"}
                  </div>
                </div>
              </div>
            )}
            {!conversation.isLoading &&
              !messages.length &&
              !draftText &&
              !pendingReplyText && (
              <Empty description="选择会话后在这里查看完整对话" />
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
            {handedBackToAi && (
              <Alert
                type="success"
                showIcon
                message="人工处理已完成，会话已交还数字员工"
                description="人工回复和处理结果已保留在对话记录中；后续问题由数字员工重新识别、选择专业员工并继续处理。"
              />
            )}
            <TextArea
              value={manualReplyText}
              onChange={(event) => setManualReplyText(event.target.value)}
              autoSize={{ minRows: 2, maxRows: 5 }}
              disabled={!assignedToMe}
              placeholder={
                assignedToMe
                  ? "输入人工回复，或到右侧生成 AI 回复建议"
                  : "接管当前会话后才能发送回复"
              }
            />
          </div>
          <div className="workbench-chat-actions">
            <Text type="secondary">
              {assignedToMe
                ? `当前负责 ${currentAgentLoad}/${currentAgentCapacity} 个活动会话`
                : assignedAgentId
                  ? `当前由 ${assignedAgentId} 负责`
                  : "当前无人负责"}
            </Text>
            <Space wrap>
              <Button
                loading={sendReply.isPending}
                disabled={!assignedToMe || !manualReplyText.trim()}
                onClick={() =>
                  sendReply.mutate({
                    resolve: false,
                    text: manualReplyText.trim(),
                  })
                }
              >
                仅发送
              </Button>
              <Button
                type="primary"
                loading={sendReply.isPending}
                disabled={!assignedToMe || !manualReplyText.trim()}
                onClick={() =>
                  sendReply.mutate({
                    resolve: true,
                    text: manualReplyText.trim(),
                  })
                }
              >
                发送并交还 AI
              </Button>
            </Space>
          </div>
        </Card>

        <Card
          className="workbench-actions"
          title="当前处理"
          extra={
            currentTicket && (
              <Tag color={statusColor(currentTicket.workflow_state)}>
                {localizedLabel(
                  workflowStateLabels,
                  currentTicket.workflow_state,
                )}
              </Tag>
            )
          }
        >
          <Tabs
            size="small"
            activeKey={actionTab}
            onChange={(key) => setActionTab(key as WorkbenchActionTab)}
            items={[
              {
                key: "handle",
                label: "接管处理",
                children: (
                  <Space
                    direction="vertical"
                    size="middle"
                    style={{ width: "100%" }}
                  >
                    <Alert
                      type="info"
                      showIcon
                      message="接管表示这段会话由你负责"
                      description="接管后其他客服不能重复回复；发送并交还 AI 后，人工回复会保留，后续问题继续由数字员工接待。"
                    />
                    {!assignedAgentId && (
                      <Button
                        type="primary"
                        loading={assignment.isPending}
                        disabled={!canTakeOver}
                        onClick={() => assignment.mutate("takeover")}
                      >
                        {canTakeOver
                          ? "接管当前会话"
                          : "当前客服已满载"}
                      </Button>
                    )}
                    {assignedToMe && (
                      <Button
                        loading={assignment.isPending}
                        onClick={() => assignment.mutate("release")}
                      >
                        释放会话
                      </Button>
                    )}
                    {(!assignedAgentId || assignedToMe) && (
                      <Button
                        loading={suggestion.isPending}
                        disabled={!conversation.data}
                        onClick={() => suggestion.mutate()}
                      >
                        {suggestion.isPending
                          ? "AI 正在检索知识并生成建议"
                          : "生成 AI 回复建议"}
                      </Button>
                    )}
                    {assignedAgentId && !assignedToMe && (
                      <Alert
                        type="warning"
                        showIcon
                        message={`会话已由 ${assignedAgentId} 接管`}
                        description="请选择其他会话，或由当前负责人释放后再操作。"
                      />
                    )}
                    {suggestionStatus && (
                      <Alert
                        type={
                          suggestionGate &&
                          suggestionGate.decision !== "AUTO_SEND"
                            ? "warning"
                            : "success"
                        }
                        showIcon
                        message="AI 回复建议已生成"
                        description={
                          <Space direction="vertical" size={2}>
                            {suggestionGate && (
                              <Text
                                type={
                                  suggestionGate.decision === "AUTO_SEND"
                                    ? "success"
                                    : "warning"
                                }
                              >
                                发送门禁：
                                {localizedLabel(
                                  gateDecisionLabels,
                                  suggestionGate.decision,
                                  suggestionGate.decision,
                                )}
                                {suggestionGate.reasons.length > 0
                                  ? `（${suggestionGate.reasons
                                      .map(gateReasonLabel)
                                      .join("；")}）`
                                  : "（证据与 Skill 校验均通过）"}
                              </Text>
                            )}
                            <Text>{suggestionStatus}</Text>
                          </Space>
                        }
                      />
                    )}
                    {suggestionError && (
                      <Alert
                        type="warning"
                        showIcon
                        message="这次没有生成 AI 回复建议"
                        description={suggestionError}
                      />
                    )}
                  </Space>
                ),
              },
              {
                key: "review",
                label: "审核建议",
                children: (
                  <Space
                    direction="vertical"
                    size="middle"
                    style={{ width: "100%" }}
                  >
                    <Alert
                      type="info"
                      showIcon
                      message="审核是确认回复能否发给用户"
                      description="这里展示数字员工草稿及其状态；AI 人工回复建议会填入中间回复框。"
                    />
                    {currentTicket?.draft ? (
                      <>
                        <Space wrap>
                          <Tag>{draftStatusLabel(currentTicket)}</Tag>
                          <Tag>
                            {currentTicket.draft.citations.length} 条知识引用
                          </Tag>
                        </Space>
                        <Paragraph className="workbench-draft-preview">
                          {currentTicket.draft.text}
                        </Paragraph>
                        {currentTicket.workflow_state ===
                          "PENDING_REVIEW" && (
                          <Alert
                            type="info"
                            showIcon
                            message="请在左侧建议回复气泡中审核"
                            description="可以直接通过、修改后发送或退回转人工；这里只查看草稿和引用依据。"
                          />
                        )}
                      </>
                    ) : (
                      <Alert
                        type="info"
                        showIcon
                        message="当前没有待审核草稿"
                        description="可以在“接管处理”标签生成人工回复建议。"
                      />
                    )}
                    <Space wrap>
                      <Segmented
                        size="small"
                        value={optimizationStyle}
                        onChange={(value) =>
                          setOptimizationStyle(
                            value as
                              | "professional"
                              | "concise"
                              | "empathetic",
                          )
                        }
                        options={[
                          { label: "专业", value: "professional" },
                          { label: "简洁", value: "concise" },
                          { label: "亲和", value: "empathetic" },
                        ]}
                      />
                      <Button
                        loading={optimize.isPending}
                        disabled={!manualReplyText.trim()}
                        onClick={() => optimize.mutate()}
                      >
                        AI 优化中间回复
                      </Button>
                    </Space>
                  </Space>
                ),
              },
              {
                key: "info",
                label: "业务信息",
                children: (
                  <Space
                    direction="vertical"
                    size="middle"
                    style={{ width: "100%" }}
                  >
                    <div>
                      <Text strong>客户与订单</Text>
                      <Paragraph
                        type="secondary"
                        style={{ margin: "4px 0 10px" }}
                      >
                        从会话中自动识别订单，用于核对客户、物流和改址资格。
                      </Paragraph>
                      {businessContext.isLoading && (
                        <Skeleton active paragraph={{ rows: 4 }} />
                      )}
                      {businessContext.error && (
                        <Alert
                          type="warning"
                          showIcon
                          message="当前无法读取业务上下文"
                          description={businessContext.error.message}
                          action={
                            <Button
                              size="small"
                              onClick={() => businessContext.refetch()}
                            >
                              重试
                            </Button>
                          }
                        />
                      )}
                      {currentBusinessContext && (
                        <Space
                          direction="vertical"
                          size="small"
                          style={{ width: "100%" }}
                        >
                          <Alert
                            type="success"
                            showIcon
                            message={
                              currentBusinessContext.resolution.matched_by
                            }
                            description={`匹配把握 ${(
                              currentBusinessContext.resolution
                                .confidence * 100
                            ).toFixed(0)}% · 来源 ${
                              currentBusinessContext.source ===
                              "mock-business"
                                ? "业务沙箱"
                                : currentBusinessContext.source
                            }`}
                          />
                          <Descriptions
                            size="small"
                            column={1}
                            items={[
                              {
                                key: "customer",
                                label: "客户",
                                children: `${currentBusinessContext.customer.display_name} · ${currentBusinessContext.customer.customer_ref}`,
                              },
                              {
                                key: "order",
                                label: "订单",
                                children: `${currentBusinessContext.order.order_id} · ${currentBusinessContext.order.item_name}`,
                              },
                              {
                                key: "order_status",
                                label: "订单与物流",
                                children: `${currentBusinessContext.order.status_label} · ${
                                  currentBusinessContext.order
                                    .logistics_status_label ?? "暂无物流状态"
                                }`,
                              },
                              {
                                key: "address",
                                label: "当前收货地址",
                                children: [
                                  currentBusinessContext.order
                                    .shipping_address.province,
                                  currentBusinessContext.order
                                    .shipping_address.city,
                                  currentBusinessContext.order
                                    .shipping_address.district,
                                  currentBusinessContext.order
                                    .shipping_address.detail,
                                ].join(" "),
                              },
                              {
                                key: "after_sales",
                                label: "售后记录",
                                children: `${currentBusinessContext.order.after_sales_cases.length} 条`,
                              },
                            ]}
                          />
                          <Button
                            type="primary"
                            disabled={!assignedToMe}
                            onClick={openAddressChangeModal}
                          >
                            {assignedToMe
                              ? "申请修改收货地址"
                              : "接管后可发起改址"}
                          </Button>
                          {addressActionMessage && (
                            <Alert
                              type="info"
                              showIcon
                              message="改址审批已创建"
                              description={addressActionMessage}
                              action={
                                addressApprovalId && onOpenApprovals ? (
                                  <Button
                                    size="small"
                                    onClick={onOpenApprovals}
                                  >
                                    去审批
                                  </Button>
                                ) : undefined
                              }
                            />
                          )}
                          {addressActionError && (
                            <Alert
                              type="error"
                              showIcon
                              message="改址申请未提交"
                              description={addressActionError}
                            />
                          )}
                        </Space>
                      )}
                    </div>
                    <Descriptions
                      size="small"
                      column={1}
                      items={[
                        {
                          key: "category",
                          label: "业务分类",
                          children: currentTicket?.classification
                            ? [
                                localizedLabel(
                                  ticketCategoryLabels,
                                  currentTicket.classification.primary,
                                ),
                                localizedLabel(
                                  ticketSecondaryLabels,
                                  currentTicket.classification.secondary,
                                ),
                              ]
                                .filter(
                                  (item, index, values) =>
                                    item !== "-" &&
                                    values.indexOf(item) === index,
                                )
                                .join(" · ")
                            : "-",
                        },
                        {
                          key: "confidence",
                          label: "分类把握",
                          children: currentTicket?.classification
                            ? `${(
                                currentTicket.classification.confidence * 100
                              ).toFixed(0)}%`
                            : "-",
                        },
                        {
                          key: "risk",
                          label: "风险",
                          children: currentTicket?.risk
                            ? `${currentTicket.risk.level} · ${currentTicket.risk.reason_codes
                                .map((reason) =>
                                  localizedLabel(
                                    riskReasonLabels,
                                    reason,
                                    reason,
                                  ),
                                )
                                .join("、")}`
                            : "-",
                        },
                        {
                          key: "queue",
                          label: "目标队列",
                          children: localizedLabel(
                            queueLabels,
                            currentTicket?.routing.queue_id,
                          ),
                        },
                        {
                          key: "human",
                          label: "人工原因",
                          children: localizedLabel(
                            humanReasonLabels,
                            currentTicket?.routing.human_reason,
                          ),
                        },
                        {
                          key: "status",
                          label: "会话状态",
                          children: currentConversation
                            ? localizedLabel(
                                conversationStatusLabels,
                                currentConversation.status,
                              )
                            : "-",
                        },
                        ...(technicalMode
                          ? [
                              {
                                key: "ticket_id",
                                label: "工单 ID",
                                children: currentTicket?.id ?? "-",
                              },
                              {
                                key: "conversation_version",
                                label: "会话版本",
                                children:
                                  currentConversation?.version ?? "-",
                              },
                              {
                                key: "employee_key",
                                label: "员工标识",
                                children:
                                  currentTicket?.employee.employee_key ??
                                  "-",
                              },
                            ]
                          : []),
                      ]}
                    />
                  </Space>
                ),
              },
            ]}
          />
          <Modal
            title="申请修改收货地址"
            open={addressModalOpen}
            okText="提交改址审批"
            cancelText="取消"
            confirmLoading={addressChange.isPending}
            okButtonProps={{
              disabled:
                !addressForm.recipient.trim() ||
                !addressForm.phone.trim() ||
                !addressForm.detail.trim(),
            }}
            onOk={() => addressChange.mutate()}
            onCancel={() => setAddressModalOpen(false)}
          >
            <Space
              direction="vertical"
              size="middle"
              style={{ width: "100%" }}
            >
              <Alert
                type="warning"
                showIcon
                message="改址属于外部写操作"
                description="提交后只创建审批单；主管批准前，系统不会修改任何物流或订单数据。"
              />
              <Space wrap>
                <Button
                  size="small"
                  onClick={() =>
                    setAddressForm((current) => ({
                      ...current,
                      phone: "13800001234",
                    }))
                  }
                >
                  填入演示手机号
                </Button>
                <Text type="secondary">
                  当前地址中的手机号已脱敏，不会回填明文。
                </Text>
              </Space>
              <Input
                addonBefore="收件人"
                value={addressForm.recipient}
                onChange={(event) =>
                  setAddressForm((current) => ({
                    ...current,
                    recipient: event.target.value,
                  }))
                }
              />
              <Input
                addonBefore="手机号"
                value={addressForm.phone}
                onChange={(event) =>
                  setAddressForm((current) => ({
                    ...current,
                    phone: event.target.value,
                  }))
                }
              />
              <Space.Compact block>
                <Input
                  placeholder="省"
                  value={addressForm.province}
                  onChange={(event) =>
                    setAddressForm((current) => ({
                      ...current,
                      province: event.target.value,
                    }))
                  }
                />
                <Input
                  placeholder="市"
                  value={addressForm.city}
                  onChange={(event) =>
                    setAddressForm((current) => ({
                      ...current,
                      city: event.target.value,
                    }))
                  }
                />
                <Input
                  placeholder="区县"
                  value={addressForm.district}
                  onChange={(event) =>
                    setAddressForm((current) => ({
                      ...current,
                      district: event.target.value,
                    }))
                  }
                />
              </Space.Compact>
              <Input
                addonBefore="详细地址"
                value={addressForm.detail}
                onChange={(event) =>
                  setAddressForm((current) => ({
                    ...current,
                    detail: event.target.value,
                  }))
                }
              />
              <Select
                style={{ width: "100%" }}
                value={addressForm.simulationMode}
                onChange={(value) =>
                  setAddressForm((current) => ({
                    ...current,
                    simulationMode: value,
                  }))
                }
                options={[
                  { value: "normal", label: "正常执行" },
                  {
                    value: "timeout_unknown",
                    label: "故障演练：超时且结果未知",
                  },
                  {
                    value: "reject",
                    label: "故障演练：外部系统明确拒绝",
                  },
                ]}
              />
              {addressForm.simulationMode !== "normal" && (
                <Alert
                  type="info"
                  showIcon
                  message="这是可重复的沙箱故障模式"
                  description="审批后才会触发。超时模式应进入对账，不能自动重复提交改址。"
                />
              )}
            </Space>
          </Modal>
          {conversation.error || ticket.error ? (
            <Alert
              type="error"
              showIcon
              message="会话数据读取失败"
              description={(conversation.error ?? ticket.error)?.message}
            />
          ) : null}
        </Card>
      </div>
    </Space>
  );
}
