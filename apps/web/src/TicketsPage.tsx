import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  createDemoTicket,
  getTicket,
  listDigitalEmployees,
  listTickets,
  retryTicketSync,
  reviewTicket,
  takeOverTicket,
} from "./api";
import type { TicketListItem } from "./types";
import { message } from "./feedback";
import {
  draftStateLabels,
  queueLabels,
  syncStateLabels,
  workflowStateLabels,
} from "./statusLabels";

const { Title, Paragraph, Text } = Typography;
const { TextArea } = Input;

const categoryLabels: Record<string, string> = {
  product_howto: "产品使用",
  access_identity: "账号权限",
  service_incident: "服务故障",
  billing_invoice: "账单发票",
  transaction_dispute: "交易争议",
  complaint_escalation: "投诉升级",
  data_privacy_security: "数据安全",
  hr_onboarding: "HR 入职",
  hr_service: "HR 服务",
  finance_service: "财务服务",
  it_support: "IT 支持",
  enterprise_service_request: "企业服务请求",
  ecommerce_presales: "电商售前咨询",
  ecommerce_aftersales: "电商售后服务",
  ecommerce_logistics: "物流查询",
  other_unclassified: "待分类",
};

function riskColor(level: string | null): string {
  if (level === "R3") return "red";
  if (level === "R2") return "volcano";
  if (level === "R1") return "gold";
  return "green";
}

function stateColor(state: string): string {
  if (state === "NEEDS_HUMAN") return "red";
  if (state === "PENDING_REVIEW") return "blue";
  if (state === "TAKEN_OVER") return "purple";
  if (state === "COMPLETED") return "green";
  return "default";
}

function DraftReviewDrawer({
  ticketId,
  open,
  onClose,
}: {
  ticketId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [editedText, setEditedText] = useState("");
  const detail = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: () => getTicket(ticketId as string),
    enabled: open && Boolean(ticketId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["tickets"] });
    await queryClient.invalidateQueries({ queryKey: ["ticket", ticketId] });
    onClose();
  };

  const review = useMutation({
    mutationFn: async (decision: "ACCEPTED" | "EDITED_AND_ACCEPTED") => {
      if (!detail.data) throw new Error("工单尚未加载");
      return reviewTicket(
        detail.data.id,
        detail.data.version,
        decision,
        decision === "EDITED_AND_ACCEPTED" ? editedText : undefined,
      );
    },
    onSuccess: refresh,
    onError: (error: Error) => message.error(error.message),
  });

  const takeover = useMutation({
    mutationFn: async () => {
      if (!detail.data) throw new Error("工单尚未加载");
      return takeOverTicket(detail.data.id, detail.data.version);
    },
    onSuccess: refresh,
    onError: (error: Error) => message.error(error.message),
  });

  const retrySync = useMutation({
    mutationFn: async () => {
      if (!detail.data) throw new Error("工单尚未加载");
      return retryTicketSync(detail.data.id, detail.data.version);
    },
    onSuccess: refresh,
    onError: (error: Error) => message.error(error.message),
  });

  const ticket = detail.data;
  return (
    <Drawer
      width={720}
      open={open}
      onClose={onClose}
      title={ticket?.subject ?? "工单详情"}
      extra={
        ticket && (
          <Tag color={stateColor(ticket.workflow_state)}>
            {workflowStateLabels[ticket.workflow_state] ?? ticket.workflow_state}
          </Tag>
        )
      }
    >
      {detail.isLoading && <Spin />}
      {ticket && (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="数字员工">
              {ticket.employee.name} · v{ticket.employee.version}
            </Descriptions.Item>
            <Descriptions.Item label="分类">
              {ticket.classification
                ? categoryLabels[ticket.classification.primary] ??
                  ticket.classification.primary
                : "待分类"}
            </Descriptions.Item>
            <Descriptions.Item label="置信度">
              {ticket.classification
                ? `${Math.round(ticket.classification.confidence * 100)}%`
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item label="优先级">
              {ticket.priority?.level ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="风险">
              <Tag color={riskColor(ticket.risk?.level ?? null)}>
                {ticket.risk?.level ?? "-"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="目标团队">
              {ticket.routing.queue_id
                ? queueLabels[ticket.routing.queue_id] ??
                  ticket.routing.queue_id
                : "待分配"}
            </Descriptions.Item>
            <Descriptions.Item label="人工原因">
              {ticket.routing.human_reason ?? "-"}
            </Descriptions.Item>
            <Descriptions.Item label="外部同步">
              <Tag color={ticket.sync.status === "SUCCEEDED" ? "green" : "blue"}>
                {syncStateLabels[ticket.sync.status] ?? ticket.sync.status}
              </Tag>
            </Descriptions.Item>
          </Descriptions>

          <Card size="small" title="客户原文">
            <Paragraph>{ticket.body}</Paragraph>
          </Card>

          <Card size="small" title="数字员工摘要">
            <Paragraph>{ticket.summary ?? "尚未生成"}</Paragraph>
            <Space wrap>
              {ticket.risk?.tags.map((tag) => (
                <Tag key={tag}>{tag}</Tag>
              ))}
            </Space>
          </Card>

          {ticket.draft ? (
            <Card
              size="small"
              title="首响草稿"
              extra={
                <Tag>
                  {draftStateLabels[ticket.draft.status] ?? ticket.draft.status}
                </Tag>
              }
            >
              <TextArea
                autoSize={{ minRows: 5 }}
                defaultValue={ticket.draft.text}
                onChange={(event) => setEditedText(event.target.value)}
              />
              {ticket.draft.citations.length > 0 && (
                <div className="citation-list">
                  <Space wrap>
                    <Text type="secondary">知识依据</Text>
                    <Tag color="cyan">
                      回答要点 {ticket.draft.claims.length} 条 / 有资料支持{" "}
                      {
                        ticket.draft.claims.filter(
                          (claim) => claim.cited_chunk_ids.length > 0,
                        ).length
                      }{" "}
                      条
                    </Tag>
                  </Space>
                  <Space wrap>
                    {ticket.draft.citations.map((citation) => (
                      <Tag key={`${citation.document_id}-${citation.version}`}>
                        《{citation.title}》v{citation.version}
                      </Tag>
                    ))}
                  </Space>
                </div>
              )}
              <Space style={{ marginTop: 16 }}>
                <Button
                  type="primary"
                  loading={review.isPending}
                  onClick={() => review.mutate("ACCEPTED")}
                >
                  采用并完成
                </Button>
                <Button
                  loading={review.isPending}
                  disabled={!editedText.trim()}
                  onClick={() => review.mutate("EDITED_AND_ACCEPTED")}
                >
                  保存修改并采用
                </Button>
                <Button
                  danger
                  loading={takeover.isPending}
                  onClick={() => takeover.mutate()}
                >
                  人工接管
                </Button>
                {(ticket.sync.status === "FAILED" ||
                  ticket.sync.status === "RETRYING") && (
                  <Button
                    loading={retrySync.isPending}
                    onClick={() => retrySync.mutate()}
                  >
                    重试外部同步
                  </Button>
                )}
              </Space>
            </Card>
          ) : (
            <Alert
              type="warning"
              showIcon
              message="该工单需要人工处理"
              description="高风险、低置信度或未分类工单不会自动生成首响。请人工接管并继续处理。"
              action={
                <Button
                  danger
                  loading={takeover.isPending}
                  onClick={() => takeover.mutate()}
                >
                  人工接管
                </Button>
              }
            />
          )}
        </Space>
      )}
    </Drawer>
  );
}

function CreateTicketModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [employeeId, setEmployeeId] = useState("");
  const employees = useQuery({
    queryKey: ["digital-employees"],
    queryFn: listDigitalEmployees,
    enabled: open,
  });
  useEffect(() => {
    if (open && !employeeId && employees.data?.length) {
      setEmployeeId(employees.data[0].id);
    }
  }, [open, employeeId, employees.data]);
  const create = useMutation({
    mutationFn: () => createDemoTicket({ subject, body, employeeId }),
    onSuccess: () => {
      message.success("工单已创建并完成数字员工处理");
      setSubject("");
      setBody("");
      onCreated();
      onClose();
    },
    onError: (error: Error) => message.error(error.message),
  });

  return (
    <Modal
      title="创建演示工单"
      open={open}
      onCancel={onClose}
      onOk={() => create.mutate()}
      okText="创建并处理"
      confirmLoading={create.isPending}
      okButtonProps={{
        disabled: !subject.trim() || !body.trim() || !employeeId,
      }}
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Select
          placeholder="选择数字员工"
          value={employeeId || undefined}
          onChange={setEmployeeId}
          loading={employees.isLoading}
          options={employees.data?.map((employee) => ({
            value: employee.id,
            label: `${employee.name} · ${employee.employee_key}`,
          }))}
          style={{ width: "100%" }}
        />
        <Input
          placeholder="工单主题"
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
        />
        <TextArea
          autoSize={{ minRows: 6 }}
          placeholder="描述客户问题。例如：请问管理员如何配置团队消息通知？"
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
        <Space wrap>
          <Button
            size="small"
            onClick={() => {
              setSubject("如何配置企业通知");
              setBody("请问管理员如何为团队配置消息通知？");
            }}
          >
            填入低风险示例
          </Button>
          <Button
            size="small"
            danger
            onClick={() => {
              setSubject("账号被盗并发生数据泄露");
              setBody("我们发现账号被盗用，怀疑已经发生数据泄露，请立即处理。");
            }}
          >
            填入高风险示例
          </Button>
        </Space>
      </Space>
    </Modal>
  );
}

export default function TicketsPage({
  technicalMode = false,
}: {
  technicalMode?: boolean;
}) {
  const queryClient = useQueryClient();
  const [selectedTicket, setSelectedTicket] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const tickets = useQuery({
    queryKey: ["tickets"],
    queryFn: listTickets,
    refetchInterval: 5_000,
  });

  const stats = useMemo(() => {
    const items = tickets.data?.items ?? [];
    return {
      total: tickets.data?.total ?? 0,
      human: items.filter((item) => item.workflow_state === "NEEDS_HUMAN").length,
      review: items.filter((item) => item.workflow_state === "PENDING_REVIEW").length,
      highRisk: items.filter(
        (item) => item.risk_level === "R2" || item.risk_level === "R3",
      ).length,
    };
  }, [tickets.data]);
  const ticketStats: Array<{ title: string; value: number; color?: string }> = [
    { title: "工单总数", value: stats.total },
    { title: "待审核草稿", value: stats.review },
    { title: "需要人工", value: stats.human, color: "#cf1322" },
    { title: "高风险工单", value: stats.highRisk, color: "#fa541c" },
  ];

  const columns: ColumnsType<TicketListItem> = [
    {
      title: "工单",
      dataIndex: "subject",
      key: "subject",
      render: (value: string, record) => (
        <Button type="link" onClick={() => setSelectedTicket(record.id)}>
          {value}
        </Button>
      ),
    },
    {
      title: "分类",
      dataIndex: "category_primary",
      render: (value: string | null) =>
        value
          ? technicalMode
            ? value
            : categoryLabels[value] ?? "其他分类"
          : "待分类",
    },
    {
      title: "优先级",
      dataIndex: "priority",
      width: 90,
      render: (value: string | null) => <Text strong>{value ?? "-"}</Text>,
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      width: 90,
      render: (value: string | null) => (
        <Tag color={riskColor(value)}>{value ?? "-"}</Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "workflow_state",
      width: 150,
      render: (value: string) => (
        <Badge
          status={value === "NEEDS_HUMAN" ? "error" : "processing"}
          text={
            <Tag color={stateColor(value)}>
              {workflowStateLabels[value] ?? "未知状态"}
            </Tag>
          }
        />
      ),
    },
    {
      title: "目标团队",
      dataIndex: "queue_id",
      width: 190,
      render: (value: string | null) =>
        value ? queueLabels[value] ?? "其他团队" : "待分配",
    },
  ];

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>
            {technicalMode ? "工单技术视图" : "内部工单与 HR 演示"}
          </Title>
          <Paragraph type="secondary">
            {technicalMode
              ? "直接查看分类码、风险等级、路由队列、草稿状态和同步结果。"
              : "查看数字员工的分类、路由和草稿，并完成人工审核。"}
          </Paragraph>
        </div>
        <Space>
          {technicalMode && <Tag color="cyan">TECH</Tag>}
          <Button onClick={() => setCreateOpen(true)}>创建演示工单</Button>
          <Button
            type="primary"
            loading={tickets.isFetching}
            onClick={() =>
              queryClient.invalidateQueries({ queryKey: ["tickets"] })
            }
          >
            刷新队列
          </Button>
        </Space>
      </div>
      <Alert
        className="boundary-alert"
        type="info"
        showIcon
        message="当前为受控演示模式"
        description="数字员工只生成分类、路由和草稿。首响由人工确认；高风险工单强制人工接管。"
      />
      {technicalMode && (
        <Card
          className="section-card"
          title="工单技术处理链"
          extra={<Tag color="cyan">LIVE DATA</Tag>}
        >
          <Descriptions
            size="small"
            column={2}
            items={[
              {
                key: "pipeline",
                label: "处理链",
                children:
                  "消息接入 → 分类 → 风险评估 → 数字员工路由 → 草稿生成 → 人工审核 → 外部同步",
              },
              {
                key: "states",
                label: "状态字段",
                children: "workflow_state / status / queue_id / version",
              },
              {
                key: "risk",
                label: "风险门禁",
                children: "R0–R3 风险等级决定自动回复、人工接管或审批",
              },
              {
                key: "trace",
                label: "审计入口",
                children: "ToolCall、模型用量、Agent Trace、Outbox 与同步记录",
              },
            ]}
          />
        </Card>
      )}
      <Row gutter={[16, 16]}>
        {ticketStats.map(({ title, value, color }) => (
          <Col xs={12} lg={6} key={title}>
            <Card className="metric-card">
              <Statistic
                title={title}
                value={value}
                valueStyle={color ? { color } : undefined}
              />
            </Card>
          </Col>
        ))}
      </Row>
      {tickets.isError && (
        <Alert
          type="error"
          showIcon
          message="无法连接 API"
          description={(tickets.error as Error).message}
        />
      )}
      <Card className="queue-card" title="工单队列">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={tickets.data?.items}
          loading={tickets.isLoading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          locale={{
            emptyText: <Empty description="暂无工单，请创建演示工单" />,
          }}
          scroll={{ x: 900 }}
        />
      </Card>
      <DraftReviewDrawer
        ticketId={selectedTicket}
        open={Boolean(selectedTicket)}
        onClose={() => setSelectedTicket(null)}
      />
      <CreateTicketModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          queryClient.invalidateQueries({ queryKey: ["tickets"] });
        }}
      />
    </Space>
  );
}
