import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Space,
  Tag,
  Typography,
} from "antd";
import type { RefObject } from "react";

import type { TicketDetail } from "../../../types";
import {
  draftStateLabels,
  groundingStatusLabels,
  localizedLabel,
  providerLabels,
  queueLabels,
  workflowStateLabels,
} from "../../../statusLabels";
import { categoryLabels, riskColor, workflowColor, type CustomerServiceSurfaceMode } from "../model";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";
import type { useReplyMutations } from "../useReplyMutations";
import type { useTicketMutations } from "../useTicketMutations";
import { LogisticsQueryPanel } from "./LogisticsQueryPanel";
import { ManualWorkAreaPanel } from "./ManualWorkAreaPanel";
import { TicketOutcomeCard } from "./TicketOutcomeCard";
import { TicketRouteTimeline } from "./TicketRouteTimeline";

const { Paragraph, Text } = Typography;
const { TextArea } = Input;

interface TicketWorkspacePanelProps {
  ticket: TicketDetail;
  conversationDetail: ReturnType<
    typeof useCustomerServiceQueries
  >["conversationDetail"];
  viewMode: CustomerServiceSurfaceMode;
  ticketPanelRef: RefObject<HTMLDivElement | null>;
  conversationListRef: RefObject<HTMLDivElement | null>;
  manualStep: number;
  ticketCompleted: boolean;
  assignedAgentId: string | null | undefined;
  currentAgentId: string;
  assignment: ReturnType<typeof useTicketMutations>["assignment"];
  replySuggestion: ReturnType<typeof useReplyMutations>["replySuggestion"];
  autoSuggestionError: string;
  setViewMode: (value: CustomerServiceSurfaceMode) => void;
  optimizationStyle: "professional" | "concise" | "empathetic";
  setOptimizationStyle: (
    value: "professional" | "concise" | "empathetic",
  ) => void;
  optimizeReply: ReturnType<typeof useReplyMutations>["optimizeReply"];
  manualReplyText: string;
  setManualReplyText: (value: string) => void;
  manualReply: ReturnType<typeof useReplyMutations>["manualReply"];
  capacityReached: boolean;
  currentAgentCapacity: number;
  currentAgentLoad: number;
  cannotTakeOver: boolean;
  assignedToAnotherAgent: boolean;
  logisticsConfigured: boolean;
  logisticsOrderId: string;
  setLogisticsOrderId: (value: string) => void;
  trackingNumber: string;
  setTrackingNumber: (value: string) => void;
  carrierCode: string;
  setCarrierCode: (value: string) => void;
  logistics: ReturnType<typeof useReplyMutations>["logistics"];
  pendingReview: boolean;
  editedText: string;
  setEditedText: (value: string) => void;
  review: ReturnType<typeof useTicketMutations>["review"];
  feedback: ReturnType<typeof useTicketMutations>["feedback"];
}

export function TicketWorkspacePanel({
  ticket,
  conversationDetail,
  viewMode,
  ticketPanelRef,
  conversationListRef,
  manualStep,
  ticketCompleted,
  assignedAgentId,
  currentAgentId,
  assignment,
  replySuggestion,
  autoSuggestionError,
  setViewMode,
  optimizationStyle,
  setOptimizationStyle,
  optimizeReply,
  manualReplyText,
  setManualReplyText,
  manualReply,
  capacityReached,
  currentAgentCapacity,
  currentAgentLoad,
  cannotTakeOver,
  assignedToAnotherAgent,
  logisticsConfigured,
  logisticsOrderId,
  setLogisticsOrderId,
  trackingNumber,
  setTrackingNumber,
  carrierCode,
  setCarrierCode,
  logistics,
  pendingReview,
  editedText,
  setEditedText,
  review,
  feedback,
}: TicketWorkspacePanelProps) {
  return (
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
      <TicketOutcomeCard ticket={ticket} />
      <ManualWorkAreaPanel
        viewMode={viewMode}
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
      />

      {String(viewMode) !== "guide" && (
      <LogisticsQueryPanel
        logisticsConfigured={logisticsConfigured}
        logisticsOrderId={logisticsOrderId}
        setLogisticsOrderId={setLogisticsOrderId}
        trackingNumber={trackingNumber}
        setTrackingNumber={setTrackingNumber}
        carrierCode={carrierCode}
        setCarrierCode={setCarrierCode}
        logistics={logistics}
      />
      )}

      <TicketRouteTimeline ticket={ticket} />

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
  );
}
