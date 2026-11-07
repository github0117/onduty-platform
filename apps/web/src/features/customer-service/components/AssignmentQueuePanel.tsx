import { Button, Card, Space, Table, Tag, Typography } from "antd";

import { riskColor } from "../model";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";
import type { useTicketMutations } from "../useTicketMutations";

const { Text } = Typography;

interface AssignmentQueuePanelProps {
  assignmentQueue: ReturnType<
    typeof useCustomerServiceQueries
  >["assignmentQueue"];
  autoAssign: ReturnType<typeof useTicketMutations>["autoAssign"];
  conversationId: string;
  selectConversation: (
    selectedConversationId: string,
    selectedTicketId: string | null,
  ) => void;
}

export function AssignmentQueuePanel({
  assignmentQueue,
  autoAssign,
  conversationId,
  selectConversation,
}: AssignmentQueuePanelProps) {
  return (
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
  );
}
