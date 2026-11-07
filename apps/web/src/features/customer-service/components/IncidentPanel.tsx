import { Alert, Button, Card, Segmented, Space, Table, Tag, Typography } from "antd";

import type { McpActionIncident } from "../../../types";
import {
  compensationStatusLabels,
  incidentFailureLabels,
  incidentStatusLabels,
  reconciliationStatusLabels,
} from "../model";
import type { IncidentResolutionOutcome } from "../useApprovalMutations";
import type { useApprovalMutations } from "../useApprovalMutations";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";

const { Text } = Typography;

interface IncidentPanelProps {
  incidentFilter: string;
  setIncidentFilter: (value: string) => void;
  mcpIncidents: ReturnType<typeof useCustomerServiceQueries>["mcpIncidents"];
  canManageIncidents: boolean;
  reconcileIncident: ReturnType<typeof useApprovalMutations>["reconcileIncident"];
  selectConversation: (
    selectedConversationId: string,
    selectedTicketId: string | null,
  ) => void;
  setIncidentNote: (value: string) => void;
  setIncidentOutcome: (value: IncidentResolutionOutcome) => void;
  setIncidentDecision: (
    value: { incident: McpActionIncident; action: "acknowledge" | "resolve" } | null,
  ) => void;
  setCompensationIncident: (value: McpActionIncident | null) => void;
  setCompensationToolId: (value: string) => void;
  setCompensationArguments: (value: string) => void;
  setCompensationNote: (value: string) => void;
}

export function IncidentPanel({
  incidentFilter,
  setIncidentFilter,
  mcpIncidents,
  canManageIncidents,
  reconcileIncident,
  selectConversation,
  setIncidentNote,
  setIncidentOutcome,
  setIncidentDecision,
  setCompensationIncident,
  setCompensationToolId,
  setCompensationArguments,
  setCompensationNote,
}: IncidentPanelProps) {
  return (
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
  );
}
