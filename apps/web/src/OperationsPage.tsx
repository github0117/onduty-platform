import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getAgentRunTrace,
  getAgentRuns,
  getCustomerValueMetrics,
  getDemoResetStatus,
  getModelMetrics,
  getRagMetrics,
  getSyncMetrics,
  getToolCalls,
  getToolMetrics,
  getWorkforceMetrics,
  listMcpConnectors,
  resetDemoData,
} from "./api";
import { useAuth } from "./auth";
import { message } from "./feedback";
import type { AgentRun, ToolCall, ToolMetricItem } from "./types";
import {
  draftStateLabels,
  eventStatusLabels,
  eventTypeLabels,
  groundingStatusLabels,
} from "./statusLabels";

const { Paragraph, Text, Title } = Typography;

const toolStatusLabels: Record<string, string> = {
  SUCCEEDED: "成功",
  FAILED: "失败",
  DENIED: "已拒绝",
  RUNNING: "执行中",
};

const runStatusLabels: Record<string, string> = {
  RUNNING: "执行中",
  SUCCEEDED: "已完成",
  WAITING_HUMAN: "等待人工",
  FAILED: "失败",
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function time(value: string): string {
  return new Date(value).toLocaleString();
}

function rateText(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : percent(value);
}

function moneyText(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "-"
    : Number(value).toFixed(4);
}

export default function OperationsPage() {
  const queryClient = useQueryClient();
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetJobId, setResetJobId] = useState<string | null>(null);
  const [valueDays, setValueDays] = useState(30);
  const { me, hasCapability, activeBusinessUnitLabel } = useAuth();
  const canResetDemo =
    hasCapability("demo.reset") && me.features.demo_reset.enabled;
  const canViewMcpConnectors = hasCapability("mcp.connectors.view");
  const tools = useQuery({ queryKey: ["metrics", "tools"], queryFn: getToolMetrics });
  const calls = useQuery({ queryKey: ["tool-calls"], queryFn: () => getToolCalls(80) });
  const runs = useQuery({
    queryKey: ["agent-runs"],
    queryFn: () => getAgentRuns(50),
    refetchInterval: 5_000,
  });
  const sync = useQuery({ queryKey: ["metrics", "sync"], queryFn: getSyncMetrics });
  const models = useQuery({
    queryKey: ["metrics", "models"],
    queryFn: getModelMetrics,
  });
  const rag = useQuery({ queryKey: ["metrics", "rag"], queryFn: getRagMetrics });
  const value = useQuery({
    queryKey: ["metrics", "value", valueDays],
    queryFn: () => getCustomerValueMetrics(valueDays),
  });
  const workforce = useQuery({
    queryKey: ["metrics", "workforce"],
    queryFn: getWorkforceMetrics,
  });
  const mcpConnectors = useQuery({
    queryKey: ["operations-mcp-connectors"],
    queryFn: listMcpConnectors,
    enabled: canViewMcpConnectors,
  });
  const trace = useQuery({
    queryKey: ["agent-trace", selectedRun?.id],
    queryFn: () => getAgentRunTrace(selectedRun!.id),
    enabled: Boolean(selectedRun),
  });
  const resetDemo = useMutation({
    mutationFn: resetDemoData,
    onSuccess: (result) => {
      setResetJobId(result.job_id);
      message.info("已提交后台任务，正在恢复演示数据…");
    },
    onError: (error: Error) => message.error(error.message),
  });
  const resetStatus = useQuery({
    queryKey: ["demo-reset", resetJobId],
    queryFn: () => getDemoResetStatus(resetJobId!),
    enabled: Boolean(resetJobId),
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const status = query.state.data?.status;
      return status === "SUCCEEDED" || status === "FAILED" ? false : 1_500;
    },
  });
  const resetStatusFailed =
    resetStatus.isError || resetStatus.isRefetchError;
  const resetBusy =
    resetDemo.isPending || (Boolean(resetJobId) && !resetStatusFailed);

  useEffect(() => {
    const job = resetStatus.data;
    if (!job) return;
    if (job.status === "SUCCEEDED") {
      message.success(job.message);
      setResetJobId(null);
      setResetOpen(false);
      queryClient.invalidateQueries().catch(() => undefined);
    } else if (job.status === "FAILED") {
      message.error(job.message);
      setResetJobId(null);
    }
  }, [queryClient, resetStatus.data]);
  const activeEmployeeCount = workforce.data?.active_employee_count ?? 0;
  const externalMcpToolCount =
    mcpConnectors.data
      ?.filter(
        (connector) =>
          connector.status === "ACTIVE" &&
          connector.code === "deepwiki-public",
      )
      .reduce((total, connector) => total + connector.tools.length, 0) ?? 0;

  const refresh = () => queryClient.invalidateQueries();

  const toolColumns: ColumnsType<ToolMetricItem> = [
    {
      title: "工具",
      dataIndex: "tool_key",
      render: (value: string) => <Text code>{value}</Text>,
    },
    { title: "调用", dataIndex: "calls", width: 80 },
    {
      title: "成功率",
      dataIndex: "success_rate",
      width: 100,
      render: (value: number) => (
        <Tag color={value >= 0.95 ? "green" : value >= 0.8 ? "gold" : "red"}>
          {percent(value)}
        </Tag>
      ),
    },
    {
      title: "P95 耗时",
      dataIndex: "p95_duration_ms",
      width: 110,
      render: (value: number) => `${Math.round(value)} ms`,
    },
  ];

  const callColumns: ColumnsType<ToolCall> = [
    {
      title: "工具",
      dataIndex: "tool_key",
      render: (value: string) => <Text code>{value}</Text>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (value: string) => (
        <Tag color={value === "SUCCEEDED" ? "green" : value === "DENIED" ? "red" : "gold"}>
          {toolStatusLabels[value] ?? "未知状态"}
        </Tag>
      ),
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      width: 80,
    },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      width: 100,
      render: (value: number | null) =>
        value === null ? "-" : `${Math.round(value)} ms`,
    },
    {
      title: "工单",
      dataIndex: "ticket_id",
      width: 110,
      render: (value: string | null) => (value ? value.slice(0, 8) : "系统"),
    },
    {
      title: "时间",
      dataIndex: "started_at",
      width: 180,
      render: time,
    },
  ];

  const runColumns: ColumnsType<AgentRun> = [
    {
      title: "执行任务",
      dataIndex: "ticket_subject",
      render: (value: string | null, run) => (
        <Space direction="vertical" size={0}>
          <Button type="link" onClick={() => setSelectedRun(run)}>
            {value ?? "系统任务"}
          </Button>
          <Text type="secondary">{run.employee_name}</Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag
          color={
            value === "SUCCEEDED"
              ? "green"
              : value === "FAILED"
                ? "red"
                : value === "WAITING_HUMAN"
                  ? "gold"
                  : "blue"
          }
        >
          {runStatusLabels[value] ?? "未知状态"}
        </Tag>
      ),
    },
    {
      title: "耗时",
      dataIndex: "duration_ms",
      width: 100,
      render: (value: number | null) =>
        value === null ? "执行中" : `${value} ms`,
    },
    {
      title: "开始时间",
      dataIndex: "started_at",
      width: 180,
      render: time,
    },
    {
      title: "Trace",
      width: 90,
      render: (_, run) => (
        <Button type="link" onClick={() => setSelectedRun(run)}>
          查看
        </Button>
      ),
    },
  ];

  const modelColumns: ColumnsType<
    NonNullable<typeof models.data>["by_purpose"][number]
  > = [
    {
      title: "用途",
      dataIndex: "purpose",
      render: (value: string) => <Text code>{value}</Text>,
    },
    { title: "调用", dataIndex: "calls", width: 90 },
    {
      title: "Token",
      dataIndex: "total_tokens",
      width: 110,
    },
    {
      title: "估算费用",
      dataIndex: "estimated_cost",
      width: 120,
      render: (value: number) => Number(value).toFixed(4),
    },
  ];

  const errors = [
    tools,
    calls,
    sync,
    models,
    rag,
    value,
    workforce,
    mcpConnectors,
  ].filter((query) => query.isError);

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <div className="page-intro">
        <div>
          <Title level={2}>运行与审计</Title>
          <Paragraph type="secondary">
            检查工具调用、模型成本、外部同步和证据质量。
          </Paragraph>
        </div>
        <Space wrap>
          {canResetDemo && (
            <Button
              loading={resetBusy}
              onClick={() => setResetOpen(true)}
            >
              检查并恢复演示数据
            </Button>
          )}
          <Button type="primary" onClick={refresh}>
            刷新运行数据
          </Button>
        </Space>
      </div>

      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          message="部分运行数据加载失败"
          description="请检查指标权限或后端服务状态。"
        />
      )}

      {(sync.data?.alerts.length ?? 0) > 0 && (
        <Alert
          type="warning"
          showIcon
          message="同步告警"
          description={sync.data?.alerts.join(" · ")}
        />
      )}

      <Row gutter={[16, 16]}>
        {[
          ["已上岗员工", activeEmployeeCount, "名"],
          ["知识有依据率", percent(rag.data?.grounding_rate ?? 0), ""],
          ["草稿采纳率", rateText(value.data?.adoption_rate), ""],
          ["单会话模型成本", moneyText(value.data?.cost_per_conversation), ""],
          ...(canViewMcpConnectors
            ? [["DeepWiki 只读工具", externalMcpToolCount, "个"] as const]
            : []),
          ["ToolCall 成功率", percent(tools.data?.success_rate ?? 0), ""],
          ["工具调用", tools.data?.calls ?? 0, "次"],
          ["模型调用", models.data?.calls ?? 0, "次"],
          ["模型 Token", models.data?.total_tokens ?? 0, ""],
          ["同步成功率", percent(sync.data?.success_rate ?? 0), ""],
          ["预算预测告警", models.data?.budget_forecast_alerts ?? 0, "人"],
        ].map(([title, value, suffix]) => (
          <Col xs={12} md={8} xl={6} key={String(title)}>
            <Card className="metric-card">
              <Statistic title={title} value={value} suffix={suffix} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        className="section-card"
        title="数字员工执行记录"
        extra={<Tag>{runs.data?.total ?? 0} 条 Run</Tag>}
      >
        <Table
          rowKey="id"
          columns={runColumns}
          dataSource={runs.data?.items}
          loading={runs.isLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无 Agent Run" /> }}
        />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card className="section-card" title="外部同步">
            <Space direction="vertical" size="middle" className="page-stack">
              <Progress
                percent={Math.round((sync.data?.success_rate ?? 0) * 100)}
                status={sync.data?.failed ? "exception" : "normal"}
              />
              <Space wrap>
                <Tag>尝试 {sync.data?.attempted ?? 0}</Tag>
                <Tag color="green">成功 {sync.data?.succeeded ?? 0}</Tag>
                <Tag color="red">失败 {sync.data?.failed ?? 0}</Tag>
                <Tag color="gold">重试 {sync.data?.retrying ?? 0}</Tag>
              </Space>
              <Text type="secondary">
                RAG 草稿 {rag.data?.draft_count ?? 0} 份，已有引用{" "}
                {rag.data?.grounded_count ?? 0} 份，回答要点引用覆盖率{" "}
                {percent(rag.data?.policy_citation_coverage ?? 0)}。检索模型{" "}
                {rag.data?.embedding_model ?? "未知"}，待重建版本{" "}
                {rag.data?.reindex_pending_versions ?? 0} 个。
              </Text>
              {rag.data?.embedding_quality === "demo" && (
                <Tag color="orange">
                  当前为本地哈希演示模式，检索质量不代表语义检索水平；配置
                  EMBEDDING_BASE_URL 与 EMBEDDING_API_KEY 后重建索引
                </Tag>
              )}
              {(rag.data?.stale_evaluation_chunk_refs ?? 0) > 0 && (
                <Tag color="red">
                  评测用例存在失效分块引用{" "}
                  {rag.data?.stale_evaluation_chunk_refs} 条，请先重建或修正用例
                </Tag>
              )}
            </Space>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card className="section-card" title="模型成本">
            <Space direction="vertical" size="middle" className="page-stack">
              <Space wrap>
                <Tag color="green">成功 {models.data?.succeeded ?? 0}</Tag>
                <Tag color="red">失败 {models.data?.failed ?? 0}</Tag>
                <Tag color="gold">预算拒绝 {models.data?.denied ?? 0}</Tag>
              </Space>
              <Text type="secondary">
                输入 Token {models.data?.input_tokens ?? 0}，输出 Token{" "}
                {models.data?.output_tokens ?? 0}，估算费用{" "}
                {Number(models.data?.estimated_cost ?? 0).toFixed(4)}。
              </Text>
              <Text type="secondary">
                当前本地模式通常没有外部 Token 成本，接入真实模型后该处会显示实际用量。
              </Text>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card
        className="section-card"
        title={`业务价值（近 ${valueDays} 天）`}
        loading={value.isLoading}
        extra={
          <Select
            size="small"
            value={valueDays}
            onChange={setValueDays}
            options={[
              { value: 7, label: "近 7 天" },
              { value: 30, label: "近 30 天" },
              { value: 90, label: "近 90 天" },
            ]}
            style={{ width: 120 }}
            aria-label="业务价值统计窗口"
          />
        }
      >
        <Space direction="vertical" size="middle" className="page-stack">
          <Space wrap>
            <Tag>草稿 {value.data?.drafts_total ?? 0}</Tag>
            <Tag color="blue">
              {draftStateLabels.AUTO_ACCEPTED}{" "}
              {value.data?.drafts_auto_accepted ?? 0}
            </Tag>
            <Tag color="gold">
              {draftStateLabels.NEEDS_REVIEW} {value.data?.drafts_pending ?? 0}
            </Tag>
            <Tag color="green">
              {draftStateLabels.ACCEPTED} {value.data?.drafts_accepted ?? 0}
            </Tag>
            <Tag color="cyan">
              {draftStateLabels.EDITED_AND_ACCEPTED}{" "}
              {value.data?.drafts_edited_and_accepted ?? 0}
            </Tag>
            <Tag color="red">
              {draftStateLabels.REJECTED} {value.data?.drafts_rejected ?? 0}
            </Tag>
            <Tag color="purple">
              {draftStateLabels.ESCALATED} {value.data?.drafts_escalated ?? 0}
            </Tag>
          </Space>
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Statistic
                title="草稿采纳率"
                value={rateText(value.data?.adoption_rate)}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="采纳后编辑率"
                value={rateText(value.data?.edit_rate)}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="单会话模型成本"
                value={moneyText(value.data?.cost_per_conversation)}
              />
            </Col>
            <Col xs={12} md={6}>
              <Statistic
                title="单采纳草稿成本"
                value={moneyText(value.data?.cost_per_adopted_draft)}
              />
            </Col>
          </Row>
          <Text type="secondary">
            窗口内工单 {value.data?.tickets_created ?? 0}，会话{" "}
            {value.data?.conversations_created ?? 0}，模型调用{" "}
            {value.data?.model_calls ?? 0} 次、Token{" "}
            {value.data?.model_tokens ?? 0}、估算费用{" "}
            {Number(value.data?.estimated_cost ?? 0).toFixed(4)}。采纳率只统计人工已审核草稿（
            {value.data?.drafts_reviewed ?? 0} 份），自动通过与待审核草稿不计入分母。
          </Text>
          {Object.keys(value.data?.grounding_counts ?? {}).length > 0 && (
            <Space wrap>
              {Object.entries(value.data?.grounding_counts ?? {}).map(
                ([status, count]) => (
                  <Tag key={status}>
                    {groundingStatusLabels[status] ?? status} {count}
                  </Tag>
                ),
              )}
            </Space>
          )}
          {value.isError && (
            <Text type="danger">
              业务价值指标加载失败，请检查指标查看权限或后端服务状态。
            </Text>
          )}
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={13}>
          <Card className="section-card" title="工具运行质量">
            <Table
              rowKey="tool_key"
              columns={toolColumns}
              dataSource={tools.data?.by_tool}
              pagination={{ pageSize: 10, showSizeChanger: true }}
              locale={{ emptyText: <Empty description="暂无工具调用" /> }}
            />
          </Card>
        </Col>
        <Col xs={24} xl={11}>
          <Card className="section-card" title="模型用途分布">
            <Table
              rowKey="purpose"
              columns={modelColumns}
              dataSource={models.data?.by_purpose}
              pagination={{ pageSize: 10, showSizeChanger: true }}
              locale={{ emptyText: <Empty description="暂无模型调用" /> }}
            />
          </Card>
        </Col>
      </Row>

      <Card className="section-card" title="最近工具调用">
        <Table
          rowKey="id"
          columns={callColumns}
          dataSource={calls.data?.items}
          loading={calls.isLoading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无审计记录" /> }}
          scroll={{ x: 760 }}
        />
      </Card>

      <Drawer
        width={720}
        open={Boolean(selectedRun)}
        onClose={() => setSelectedRun(null)}
        title={`执行 Trace · ${selectedRun?.ticket_subject ?? "系统任务"}`}
        extra={
          selectedRun && (
            <Tag
              color={
                selectedRun.status === "SUCCEEDED"
                  ? "green"
                  : selectedRun.status === "FAILED"
                    ? "red"
                    : "gold"
              }
            >
              {runStatusLabels[selectedRun.status] ?? selectedRun.status}
            </Tag>
          )
        }
      >
        {trace.isLoading && <Text type="secondary">正在加载 Trace…</Text>}
        {trace.isError && (
          <Alert
            type="error"
            showIcon
            message="Trace 加载失败"
            description={(trace.error as Error).message}
          />
        )}
        {trace.data && (
          <Space direction="vertical" size="large" className="page-stack">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="数字员工">
                {trace.data.run.employee_name}
              </Descriptions.Item>
              <Descriptions.Item label="工作流">
                {trace.data.run.workflow_key}
              </Descriptions.Item>
              <Descriptions.Item label="Run ID" span={2}>
                <Text code>{trace.data.run.id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="开始时间" span={2}>
                {time(trace.data.run.started_at)}
              </Descriptions.Item>
            </Descriptions>
            <Timeline
              items={trace.data.events.map((event) => ({
                color:
                  event.status === "FAILED" || event.status === "DENIED"
                    ? "red"
                    : event.event_type === "model"
                      ? "blue"
                      : event.event_type === "tool"
                        ? "cyan"
                        : "green",
                children: (
                  <div className="trace-event">
                    <Space wrap>
                      <Text strong>{event.title}</Text>
                      <Tag>
                        {eventTypeLabels[event.event_type] ?? "系统事件"}
                      </Tag>
                      <Tag>
                        {eventStatusLabels[event.status] ?? "状态已更新"}
                      </Tag>
                      {event.duration_ms !== null && (
                        <Text type="secondary">{event.duration_ms} ms</Text>
                      )}
                    </Space>
                    <Text type="secondary" className="trace-time">
                      {time(event.timestamp)}
                    </Text>
                    {Object.keys(event.detail).length > 0 && (
                      <pre className="trace-detail">
                        {JSON.stringify(event.detail, null, 2)}
                      </pre>
                    )}
                  </div>
                ),
              }))}
            />
          </Space>
        )}
      </Drawer>

      <Modal
        title="检查并恢复演示数据？"
        open={resetOpen}
        onCancel={() => {
          if (!resetBusy) setResetOpen(false);
        }}
        onOk={() => resetDemo.mutate()}
        okText={resetBusy ? "恢复中…" : "开始恢复"}
        cancelText="关闭"
        confirmLoading={resetBusy}
        okButtonProps={{ disabled: resetBusy }}
        cancelButtonProps={{ disabled: resetBusy }}
      >
        <Space direction="vertical" size="middle">
          <Text>
            系统会检查并补齐固定演示所需的员工、知识、工单、商品和内容任务。
          </Text>
          <Alert
            type="info"
            showIcon
            message="这是租户隔离的幂等恢复，不会删除你手工创建的数据"
            description={`任务只作用于 ${activeBusinessUnitLabel}，在后台执行并轮询进度；固定演示数据已存在时会更新或复用。仅演示或开发环境可执行。`}
          />
          {resetStatus.data && (
            <Alert
              type={
                resetStatus.data.status === "FAILED" ? "error" : "info"
              }
              showIcon
              message={
                resetStatus.data.status === "QUEUED"
                  ? "任务已排队"
                  : resetStatus.data.status === "RUNNING"
                    ? "正在恢复演示数据"
                    : resetStatus.data.status === "FAILED"
                      ? "恢复失败"
                      : "恢复完成"
              }
              description={resetStatus.data.message}
            />
          )}
          {resetStatusFailed && (
            <Alert
              type="warning"
              showIcon
              message="暂时无法获取任务状态"
              description="后台任务可能仍在运行，请重新查询或稍后刷新页面查看结果。"
              action={
                <Button
                  size="small"
                  onClick={() => resetStatus.refetch()}
                >
                  重新查询
                </Button>
              }
            />
          )}
        </Space>
      </Modal>
    </Space>
  );
}
