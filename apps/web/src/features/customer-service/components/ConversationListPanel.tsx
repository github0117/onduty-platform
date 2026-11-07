import { Card, Segmented, Space, Table, Tag, Typography } from "antd";
import type { RefObject } from "react";

import type { CustomerConversation } from "../../../types";
import {
  conversationStatusLabels,
  localizedLabel,
  workflowStateLabels,
} from "../../../statusLabels";
import { riskColor, workflowColor, type ConversationFilter } from "../model";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";

const { Text } = Typography;

interface ConversationListPanelProps {
  conversationListRef: RefObject<HTMLDivElement | null>;
  presence: ReturnType<typeof useCustomerServiceQueries>["presence"];
  conversations: ReturnType<typeof useCustomerServiceQueries>["conversations"];
  conversationFilter: ConversationFilter;
  setConversationFilter: (value: ConversationFilter) => void;
  conversationItems: CustomerConversation[];
  filteredConversations: CustomerConversation[];
  currentAgentId: string;
  conversationId: string;
  selectConversation: (
    selectedConversationId: string,
    selectedTicketId: string | null,
  ) => void;
}

export function ConversationListPanel({
  conversationListRef,
  presence,
  conversations,
  conversationFilter,
  setConversationFilter,
  conversationItems,
  filteredConversations,
  currentAgentId,
  conversationId,
  selectConversation,
}: ConversationListPanelProps) {
  return (
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
  );
}
