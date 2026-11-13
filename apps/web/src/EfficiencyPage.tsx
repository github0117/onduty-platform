import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  getEfficiencyAssumptions,
  getEfficiencySummary,
  listEfficiencyLedger,
  rebuildEfficiencyLedger,
  updateEfficiencyAssumptions,
} from "./api";
import { useAuth } from "./auth";
import { message } from "./feedback";
import type {
  EfficiencyAssumption,
  EfficiencyDailyPoint,
  EfficiencyEmployeeBreakdown,
  EfficiencyLedgerEntry,
  EfficiencySourceBreakdown,
} from "./types";

const { Paragraph, Text, Title } = Typography;

const sourceLabels: Record<string, string> = {
  TICKET_AUTO_RESOLVED: "工单自动完成",
  CONVERSATION_RESOLVED: "会话自动解决",
  ECOMMERCE_LISTING_COMPLETED: "电商上架完成",
};

const sourceHints: Record<string, string> = {
  TICKET_AUTO_RESOLVED: "数字员工完成工单处理，未发生人工接管",
  CONVERSATION_RESOLVED: "数字员工完成会话并标记解决，未发生人工接管",
  ECOMMERCE_LISTING_COMPLETED: "数字员工完成电商上架任务内容生成与发布",
};

interface AssumptionDraft {
  currency: string;
  hourly_labor_cost: number;
  minutes_per_ticket: number;
  minutes_per_conversation: number;
  minutes_per_listing: number;
}

function draftFrom(value: EfficiencyAssumption): AssumptionDraft {
  return {
    currency: value.currency,
    hourly_labor_cost: value.hourly_labor_cost,
    minutes_per_ticket: value.minutes_per_ticket,
    minutes_per_conversation: value.minutes_per_conversation,
    minutes_per_listing: value.minutes_per_listing,
  };
}

function formatMoney(value: number, currency: string): string {
  return `${value.toFixed(2)} ${currency}`;
}

export default function EfficiencyPage() {
  const queryClient = useQueryClient();
  const { hasCapability, activeBusinessUnitLabel } = useAuth();
  const canManage = hasCapability("operations.manage");
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [draft, setDraft] = useState<AssumptionDraft | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["efficiency-summary", days],
    queryFn: () => getEfficiencySummary(days),
  });
  const assumptionsQuery = useQuery({
    queryKey: ["efficiency-assumptions"],
    queryFn: getEfficiencyAssumptions,
  });
  const ledgerQuery = useQuery({
    queryKey: ["efficiency-ledger", days, page],
    queryFn: () => listEfficiencyLedger(days, pageSize, (page - 1) * pageSize),
  });

  useEffect(() => {
    if (assumptionsQuery.data) {
      setDraft(draftFrom(assumptionsQuery.data));
    }
  }, [assumptionsQuery.data]);

  useEffect(() => {
    setPage(1);
  }, [days]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("假设尚未加载完成");
      if (draft.hourly_labor_cost <= 0) {
        throw new Error("时薪必须大于 0");
      }
      for (const minutes of [
        draft.minutes_per_ticket,
        draft.minutes_per_conversation,
        draft.minutes_per_listing,
      ]) {
        if (minutes < 0) throw new Error("分钟数不能为负数");
      }
      return updateEfficiencyAssumptions(draft);
    },
    onSuccess: (data) => {
      message.success(`假设已保存（版本 ${data.version}），仅影响后续生成的账本条目`);
      void queryClient.invalidateQueries({ queryKey: ["efficiency-assumptions"] });
      void queryClient.invalidateQueries({ queryKey: ["efficiency-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["efficiency-ledger"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const rebuildMutation = useMutation({
    mutationFn: () => rebuildEfficiencyLedger(days),
    onSuccess: (data) => {
      message.success(
        `已重新计算：新增 ${data.created} 条，已存在 ${data.skipped_existing} 条，不重复计入 ${data.skipped_ineligible} 条`,
      );
      void queryClient.invalidateQueries({ queryKey: ["efficiency-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["efficiency-ledger"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const summary = summaryQuery.data;
  const currency = summary?.currency ?? draft?.currency ?? "CNY";
  const sourceRows = useMemo(() => summary?.by_source ?? [], [summary]);
  const employeeRows = useMemo(() => summary?.by_employee ?? [], [summary]);
  const dailyRows = useMemo(() => summary?.daily ?? [], [summary]);

  const sourceColumns: ColumnsType<EfficiencySourceBreakdown> = [
    {
      title: "来源",
      dataIndex: "source_type",
      render: (value: string) => (
        <Space direction="vertical" size={0}>
          <Text strong>{sourceLabels[value] ?? value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {sourceHints[value] ?? value}
          </Text>
        </Space>
      ),
    },
    {
      title: "条数",
      dataIndex: "entries",
      width: 90,
      align: "right",
    },
    {
      title: "人时节省",
      dataIndex: "human_hours_saved",
      width: 120,
      align: "right",
      render: (value: number) => `${value.toFixed(2)} 小时`,
    },
    {
      title: "人力成本节省",
      dataIndex: "labor_cost_saved",
      width: 160,
      align: "right",
      render: (value: number) => formatMoney(value, currency),
    },
  ];

  const employeeColumns: ColumnsType<EfficiencyEmployeeBreakdown> = [
    {
      title: "数字员工",
      dataIndex: "employee_name",
      render: (value: string) => <Text strong>{value}</Text>,
    },
    { title: "条数", dataIndex: "entries", width: 90, align: "right" },
    {
      title: "人时节省",
      dataIndex: "human_hours_saved",
      width: 120,
      align: "right",
      render: (value: number) => `${value.toFixed(2)} 小时`,
    },
    {
      title: "人力成本节省",
      dataIndex: "labor_cost_saved",
      width: 160,
      align: "right",
      render: (value: number) => formatMoney(value, currency),
    },
  ];

  const dailyColumns: ColumnsType<EfficiencyDailyPoint> = [
    { title: "日期", dataIndex: "day", width: 140 },
    { title: "条数", dataIndex: "entries", width: 90, align: "right" },
    {
      title: "人时节省",
      dataIndex: "human_hours_saved",
      width: 120,
      align: "right",
      render: (value: number) => `${value.toFixed(2)} 小时`,
    },
    {
      title: "人力成本节省",
      dataIndex: "labor_cost_saved",
      width: 160,
      align: "right",
      render: (value: number) => formatMoney(value, currency),
    },
  ];

  const ledgerColumns: ColumnsType<EfficiencyLedgerEntry> = [
    {
      title: "发生时间",
      dataIndex: "occurred_at",
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "来源",
      dataIndex: "source_type",
      render: (value: string) => sourceLabels[value] ?? value,
    },
    {
      title: "对象",
      dataIndex: "source_id",
      width: 260,
      render: (value: string) => (
        <Text copyable={{ text: value }} style={{ fontSize: 12 }}>
          {value}
        </Text>
      ),
    },
    { title: "数字员工", dataIndex: "employee_name", width: 140 },
    {
      title: "人时",
      dataIndex: "human_minutes_saved",
      width: 100,
      align: "right",
      render: (value: number) => `${value.toFixed(2)} 分钟`,
    },
    {
      title: "人力成本",
      dataIndex: "labor_cost_saved",
      width: 140,
      align: "right",
      render: (value: number) => formatMoney(value, currency),
    },
    {
      title: "假设版本",
      dataIndex: "assumption_version",
      width: 110,
      align: "right",
      render: (value: number | null) =>
        value === null ? "—" : <Tag>v{value}</Tag>,
    },
  ];

  const assumptionValid =
    draft !== null &&
    draft.hourly_labor_cost > 0 &&
    draft.minutes_per_ticket >= 0 &&
    draft.minutes_per_conversation >= 0 &&
    draft.minutes_per_listing >= 0;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space direction="vertical" size={4}>
        <Title level={3} style={{ margin: 0 }}>
          效率账本
        </Title>
        <Text type="secondary">
          当前业务单元：{activeBusinessUnitLabel}。人时与 ROI 均基于可配置假设，
          不是财务口径。
        </Text>
      </Space>

      <Space wrap>
        <Select
          value={days}
          onChange={setDays}
          style={{ width: 140 }}
          options={[
            { value: 7, label: "最近 7 天" },
            { value: 30, label: "最近 30 天" },
            { value: 90, label: "最近 90 天" },
          ]}
        />
        <Button
          type="primary"
          loading={rebuildMutation.isPending}
          disabled={!canManage}
          onClick={() => rebuildMutation.mutate()}
        >
          重新计算
        </Button>
        {!canManage && (
          <Text type="secondary">只有主管或管理员可以重新计算账本。</Text>
        )}
      </Space>

      {summaryQuery.isError && (
        <Alert
          type="error"
          showIcon
          message="效率汇总加载失败"
          description={summaryQuery.error.message}
          action={
            <Button size="small" onClick={() => void summaryQuery.refetch()}>
              重试
            </Button>
          }
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8} xl={4}>
          <Card loading={summaryQuery.isLoading}>
            <Statistic
              title="人时节省"
              value={summary?.human_hours_saved ?? 0}
              precision={2}
              suffix="小时"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8} xl={5}>
          <Card loading={summaryQuery.isLoading}>
            <Statistic
              title="人力成本节省"
              value={summary?.labor_cost_saved ?? 0}
              precision={2}
              suffix={currency}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8} xl={5}>
          <Card loading={summaryQuery.isLoading}>
            <Statistic
              title="模型成本"
              value={summary?.model_cost ?? 0}
              precision={2}
              suffix={currency}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8} xl={5}>
          <Card loading={summaryQuery.isLoading}>
            <Statistic
              title="ROI 倍数"
              value={summary?.roi === null || summary?.roi === undefined ? "—" : summary.roi}
              precision={summary?.roi === null || summary?.roi === undefined ? 0 : 2}
              suffix={summary?.roi === null || summary?.roi === undefined ? "" : "×"}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8} xl={5}>
          <Card loading={summaryQuery.isLoading}>
            <Statistic
              title="净收益"
              value={summary?.net_saving ?? 0}
              precision={2}
              suffix={currency}
              valueStyle={{
                color:
                  summary && summary.net_saving < 0 ? "#cf1322" : undefined,
              }}
            />
          </Card>
        </Col>
      </Row>

      {summary?.mixed_currency && (
        <Alert
          type="warning"
          showIcon
          message="当前窗口存在多币种账本条目"
          description="汇总不会把不同币种直接相加，请按业务单元拆分查看。"
        />
      )}

      <Card title="计量口径">
        <Space direction="vertical" size={4}>
          {summary?.basis.map((item) => (
            <Text key={item} type="secondary">
              · {item}
            </Text>
          ))}
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card title="按来源">
            <Table
              size="small"
              rowKey="source_type"
              columns={sourceColumns}
              dataSource={sourceRows}
              pagination={false}
              scroll={{ x: 620 }}
              locale={{ emptyText: "当前窗口暂无效率记录" }}
            />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card title="按数字员工">
            <Table
              size="small"
              rowKey={(row) => row.employee_id ?? "unbound"}
              columns={employeeColumns}
              dataSource={employeeRows}
              pagination={false}
              scroll={{ x: 620 }}
              locale={{ emptyText: "当前窗口暂无效率记录" }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="每日趋势">
        <Table
          size="small"
          rowKey="day"
          columns={dailyColumns}
          dataSource={dailyRows}
          pagination={false}
          scroll={{ x: 620 }}
          locale={{ emptyText: "当前窗口暂无效率记录" }}
        />
      </Card>

      <Card
        title="人力成本假设"
        extra={
          assumptionsQuery.data && (
            <Space>
              <Tag color={assumptionsQuery.data.persisted ? "blue" : "default"}>
                {assumptionsQuery.data.persisted
                  ? `已保存 v${assumptionsQuery.data.version}`
                  : "使用默认值"}
              </Tag>
            </Space>
          )
        }
      >
        {draft && (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Row gutter={[16, 16]}>
              <Col xs={24} sm={12} lg={6}>
                <Text type="secondary">币种</Text>
                <Input
                  value={draft.currency}
                  disabled={!canManage}
                  maxLength={8}
                  onChange={(event) =>
                    setDraft({ ...draft, currency: event.target.value })
                  }
                />
              </Col>
              <Col xs={24} sm={12} lg={6}>
                <Text type="secondary">时薪（元/小时）</Text>
                <InputNumber
                  min={0.01}
                  step={1}
                  style={{ width: "100%" }}
                  value={draft.hourly_labor_cost}
                  disabled={!canManage}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      hourly_labor_cost: Number(value ?? 0),
                    })
                  }
                />
              </Col>
              <Col xs={24} sm={12} lg={4}>
                <Text type="secondary">每张工单（分钟）</Text>
                <InputNumber
                  min={0}
                  step={1}
                  style={{ width: "100%" }}
                  value={draft.minutes_per_ticket}
                  disabled={!canManage}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      minutes_per_ticket: Number(value ?? 0),
                    })
                  }
                />
              </Col>
              <Col xs={24} sm={12} lg={4}>
                <Text type="secondary">每次会话（分钟）</Text>
                <InputNumber
                  min={0}
                  step={1}
                  style={{ width: "100%" }}
                  value={draft.minutes_per_conversation}
                  disabled={!canManage}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      minutes_per_conversation: Number(value ?? 0),
                    })
                  }
                />
              </Col>
              <Col xs={24} sm={12} lg={4}>
                <Text type="secondary">每个上架任务（分钟）</Text>
                <InputNumber
                  min={0}
                  step={1}
                  style={{ width: "100%" }}
                  value={draft.minutes_per_listing}
                  disabled={!canManage}
                  onChange={(value) =>
                    setDraft({
                      ...draft,
                      minutes_per_listing: Number(value ?? 0),
                    })
                  }
                />
              </Col>
            </Row>
            <Space>
              <Button
                type="primary"
                loading={saveMutation.isPending}
                disabled={!canManage || !assumptionValid}
                onClick={() => saveMutation.mutate()}
              >
                保存假设
              </Button>
              <Text type="secondary">
                已生成的账本条目不会因假设变化而改写。
              </Text>
            </Space>
          </Space>
        )}
      </Card>

      <Card
        title="账本明细"
        extra={
          <Text type="secondary">
            共 {ledgerQuery.data?.total ?? 0} 条
          </Text>
        }
      >
        {ledgerQuery.isError ? (
          <Alert
            type="error"
            showIcon
            message="账本明细加载失败"
            description={ledgerQuery.error.message}
            action={
              <Button size="small" onClick={() => void ledgerQuery.refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <Table
            size="small"
            rowKey="id"
            loading={ledgerQuery.isLoading}
            columns={ledgerColumns}
            dataSource={ledgerQuery.data?.items ?? []}
            scroll={{ x: 1000 }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前窗口暂无效率记录"
                />
              ),
            }}
            pagination={{
              current: page,
              pageSize,
              total: ledgerQuery.data?.total ?? 0,
              showSizeChanger: false,
              onChange: setPage,
            }}
          />
        )}
      </Card>

      {summaryQuery.isLoading && <Paragraph>正在加载效率账本…</Paragraph>}
    </Space>
  );
}
