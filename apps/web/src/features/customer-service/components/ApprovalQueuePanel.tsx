import {
  Alert,
  Button,
  Card,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import type { McpToolApproval } from "../../../types";
import { approvalStatusColor, approvalStatusLabels } from "../model";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";

const { Text } = Typography;

interface ApprovalQueuePanelProps {
  approvalFilter: string;
  setApprovalFilter: (value: string) => void;
  mcpApprovals: ReturnType<typeof useCustomerServiceQueries>["mcpApprovals"];
  canDecideApprovals: boolean;
  selectConversation: (
    selectedConversationId: string,
    selectedTicketId: string | null,
  ) => void;
  setApprovalNote: (value: string) => void;
  setApprovalDecision: (
    value: { approval: McpToolApproval; decision: "APPROVE" | "REJECT" } | null,
  ) => void;
}

export function ApprovalQueuePanel({
  approvalFilter,
  setApprovalFilter,
  mcpApprovals,
  canDecideApprovals,
  selectConversation,
  setApprovalNote,
  setApprovalDecision,
}: ApprovalQueuePanelProps) {
  return (
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
  );
}
