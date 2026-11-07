import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  listBusinessServiceEntries,
  listDigitalEmployeeRouteDecisions,
  listDigitalEmployeeRouteIntentConflicts,
  listDigitalEmployeeRouteRules,
  replaceBusinessServiceEntryEmployees,
  updateDigitalEmployeeRouteRule,
} from "../../api";
import { message } from "../../feedback";
import {
  accuracyPercent,
  enabledCaseCount,
  filterEvaluationResults,
  useRouteEvaluation,
} from "./useRouteEvaluation";
import type {
  BusinessServiceEntry,
  DigitalEmployee,
  DigitalEmployeeRouteCandidate,
  DigitalEmployeeRouteEvaluationCase,
  DigitalEmployeeRouteEvaluationDataset,
  DigitalEmployeeRouteIntentConflictList,
  DigitalEmployeeRouteRule,
} from "../../types";
import {
  RouteEvidence,
  routeConfidenceColor,
  routeDecisionEmployee,
  routeDecisionReason,
  routeDecisionSource,
  routeEvaluationDatasetLabels,
  routeReasonColor,
  routeReasonLabels,
} from "./shared";

const { Paragraph, Text, Title } = Typography;
const { TextArea } = Input;

export function DigitalEmployeeRoutingCard({
  employees,
  onNavigate,
}: {
  employees: DigitalEmployee[];
  onNavigate?: (path: string) => void;
}) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<DigitalEmployeeRouteRule | null>(null);
  const [intents, setIntents] = useState("");
  const [priority, setPriority] = useState(100);
  const [fallback, setFallback] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [showAllRules, setShowAllRules] = useState(false);
  const [editingEntry, setEditingEntry] =
    useState<BusinessServiceEntry | null>(null);
  const [entryEmployeeIds, setEntryEmployeeIds] = useState<string[]>([]);
  const businessEntries = useQuery({
    queryKey: ["business-service-entries"],
    queryFn: listBusinessServiceEntries,
  });
  const rules = useQuery({
    queryKey: ["digital-employee-route-rules"],
    queryFn: listDigitalEmployeeRouteRules,
  });
  const decisions = useQuery({
    queryKey: ["digital-employee-route-decisions"],
    queryFn: listDigitalEmployeeRouteDecisions,
    refetchInterval: 10_000,
  });
  const employeeName = (employeeId: string) =>
    employees.find((employee) => employee.id === employeeId)?.name ??
    employeeId.slice(0, 8);
  const employeeStatus = (employeeId: string) =>
    employees.find((employee) => employee.id === employeeId)?.status;
  const currentEmployeeIds = new Set(
    employees
      .filter(
        (employee) =>
          employee.status === "ACTIVE" || employee.status === "TRIAL",
      )
      .map((employee) => employee.id),
  );
  const entryMembershipCount = new Map<string, number>();
  for (const entry of businessEntries.data ?? []) {
    for (const employee of entry.employees) {
      if (!employee.enabled) continue;
      entryMembershipCount.set(
        employee.employee_id,
        (entryMembershipCount.get(employee.employee_id) ?? 0) + 1,
      );
    }
  }
  const currentRules = (rules.data ?? []).filter((rule) => {
    const status = employeeStatus(rule.employee_id);
    return (
      rule.enabled &&
      (status === "ACTIVE" || status === "TRIAL")
    );
  });
  const displayedRules = showAllRules ? rules.data ?? [] : currentRules;
  const save = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("请选择路由规则");
      return updateDigitalEmployeeRouteRule(editing.employee_id, {
        intents: intents
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
        categories: editing.categories,
        channels: editing.channels,
        priority,
        fallback,
        enabled,
      });
    },
    onSuccess: async () => {
      message.success("数字员工路由已保存");
      setEditing(null);
      await queryClient.invalidateQueries({
        queryKey: ["digital-employee-route-rules"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["digital-employee-route-decisions"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const openEditor = (rule: DigitalEmployeeRouteRule) => {
    setEditing(rule);
    setIntents(rule.intents.join(", "));
    setPriority(rule.priority);
    setFallback(rule.fallback);
    setEnabled(rule.enabled);
  };
  const saveEntryEmployees = useMutation({
    mutationFn: () => {
      if (!editingEntry) throw new Error("请选择业务入口");
      if (entryEmployeeIds.length === 0) {
        throw new Error("业务入口至少需要一名数字员工");
      }
      return replaceBusinessServiceEntryEmployees(
        editingEntry.id,
        entryEmployeeIds.map((employeeId, index) => ({
          employeeId,
          roleType:
            employeeId === editingEntry.default_employee_id
              ? "PRIMARY"
              : employeeId === editingEntry.fallback_employee_id
                ? "FALLBACK"
                : "SPECIALIST",
          priority: (index + 1) * 10,
        })),
      );
    },
    onSuccess: async () => {
      message.success("业务入口员工池已更新");
      setEditingEntry(null);
      await queryClient.invalidateQueries({
        queryKey: ["business-service-entries"],
      });
    },
    onError: (error: Error) => message.error(error.message),
  });
  const openEntryEditor = (entry: BusinessServiceEntry) => {
    setEditingEntry(entry);
    setEntryEmployeeIds(
      entry.employees.map((employee) => employee.employee_id),
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        className="section-card"
        title="业务入口与员工池"
        loading={businessEntries.isLoading}
      >
        <Paragraph type="secondary">
          一个业务入口可以绑定多名数字员工。客户进入入口后，系统只会在该入口的
          员工池中选择处理人员，不再由页面写死某一个员工。
        </Paragraph>
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {(businessEntries.data ?? []).map((entry) => {
            const sharedEmployeeCount = entry.employees.filter(
              (employee) =>
                (entryMembershipCount.get(employee.employee_id) ?? 0) > 1,
            ).length;
            return (
              <Card
                key={entry.id}
                size="small"
                type="inner"
                title={entry.name}
                extra={
                  <Space wrap size={6}>
                    {sharedEmployeeCount > 0 && (
                      <Tag color="gold">
                        {sharedEmployeeCount} 名员工跨入口复用
                      </Tag>
                    )}
                    <Button
                      size="small"
                      onClick={() => openEntryEditor(entry)}
                    >
                      配置员工池
                    </Button>
                  </Space>
                }
              >
                <Space
                  direction="vertical"
                  size={8}
                  style={{ width: "100%" }}
                >
                  <Text type="secondary">{entry.description}</Text>
                  <Space wrap size={6}>
                    <Tag color="cyan">{entry.domain}</Tag>
                    <Tag>{entry.channel}</Tag>
                    <Tag
                      color={
                        entry.status === "ACTIVE" ? "green" : "default"
                      }
                    >
                      {entry.status === "ACTIVE" ? "当前可用" : "已停用"}
                    </Tag>
                    <Tag>{entry.employees.length} 名数字员工</Tag>
                  </Space>
                  <Space wrap size={6}>
                    {entry.employees.map((employee) => {
                      const membership =
                        entryMembershipCount.get(
                          employee.employee_id,
                        ) ?? 0;
                      return (
                        <Tag
                          key={employee.employee_id}
                          color={
                            employee.role_type === "PRIMARY"
                              ? "blue"
                              : employee.role_type === "FALLBACK"
                                ? "gold"
                                : "default"
                          }
                        >
                          {employee.employee_name}
                          {employee.role_type === "PRIMARY"
                            ? " · 默认"
                            : employee.role_type === "FALLBACK"
                              ? " · 兜底"
                              : " · 专业"}
                          {membership > 1
                            ? ` · 复用 ${membership} 个入口`
                            : ""}
                        </Tag>
                      );
                    })}
                  </Space>
                </Space>
              </Card>
            );
          })}
        </Space>
      </Card>
      <Card
        className="section-card"
        title="意图派单规则"
      extra={
        <Space wrap>
          <Button
            size="small"
            onClick={() => onNavigate?.("/employees/route-evaluation")}
          >
            打开路由评测
          </Button>
          <Select
            aria-label="路由规则范围"
            value={showAllRules ? "ALL" : "CURRENT"}
            onChange={(value) => setShowAllRules(value === "ALL")}
            options={[
              { value: "CURRENT", label: "当前生效" },
              { value: "ALL", label: "全部规则" },
            ]}
            style={{ width: 120 }}
          />
          <Tag>
            {displayedRules.length} / {rules.data?.length ?? 0} 条规则
          </Tag>
        </Space>
      }
    >
      <Paragraph type="secondary">
        工单没有手动指定员工时，系统先按这些意图匹配岗位；没有命中再使用兜底员工。
      </Paragraph>
      <Table
        rowKey="id"
        size="small"
        loading={rules.isLoading}
        dataSource={displayedRules}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={[
          {
            title: "数字员工",
            dataIndex: "employee_id",
            render: (value: string) => employeeName(value),
          },
          {
            title: "路由意图",
            dataIndex: "intents",
            render: (value: string[]) => value.join("、") || "未配置",
          },
          { title: "优先级", dataIndex: "priority", width: 90 },
          {
            title: "兜底",
            dataIndex: "fallback",
            width: 80,
            render: (value: boolean) => (value ? <Tag>兜底</Tag> : "-"),
          },
          {
            title: "启用",
            dataIndex: "enabled",
            width: 80,
            render: (value: boolean) => (
              <Tag color={value ? "green" : "default"}>
                {value ? "启用" : "停用"}
              </Tag>
            ),
          },
          {
            title: "操作",
            width: 100,
            render: (_value, rule) => (
              <Button type="link" onClick={() => openEditor(rule)}>
                编辑路由
              </Button>
            ),
          },
        ]}
      />
      <Title level={5} style={{ marginTop: 20 }}>
        最近路由结果
      </Title>
      <Table
        rowKey="id"
        size="small"
        loading={decisions.isLoading}
        dataSource={decisions.data?.items.slice(0, 10)}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        expandable={{
          expandedRowRender: (row) => (
            <RouteEvidence candidates={row.candidates} />
          ),
          rowExpandable: (row) => row.candidates.length > 0,
        }}
        columns={[
          {
            title: "选中员工",
            dataIndex: "selected_employee_key",
            render: (_value, row) => {
              const employee = routeDecisionEmployee(row);
              return (
                <Space direction="vertical" size={0}>
                  <Text strong>
                    {employee?.employee_name ?? "未识别员工"}
                  </Text>
                  <Text type="secondary">
                    {routeDecisionSource(row)}
                  </Text>
                </Space>
              );
            },
          },
          {
            title: "路由原因",
            dataIndex: "reason",
            render: (_value: string, row) => (
              <Space direction="vertical" size={4}>
                <Tag color={routeReasonColor(row.reason_code)}>
                  {routeReasonLabels[row.reason_code] ?? "系统自动判断"}
                </Tag>
                <Text>{routeDecisionReason(row)}</Text>
              </Space>
            ),
          },
          {
            title: "候选",
            dataIndex: "candidates",
            render: (
              value: DigitalEmployeeRouteCandidate[],
            ) => {
              const currentCandidates = value.filter((item) =>
                currentEmployeeIds.has(item.employee_id),
              );
              const names = [
                ...new Set(
                  currentCandidates
                    .map((item) => item.employee_name)
                    .filter(Boolean),
                ),
              ];
              const historicalCount =
                value.length - currentCandidates.length;
              return (
                <Space direction="vertical" size={0}>
                  <Text>
                    {names.length > 0
                      ? names.slice(0, 3).join(" / ")
                      : "当前没有可用候选"}
                  </Text>
                  <Text type="secondary">
                    共 {value.length} 个候选
                    {historicalCount > 0
                      ? `，其中 ${historicalCount} 个已停用或不可用`
                      : ""}
                    ，展开查看评分和排除原因
                  </Text>
                </Space>
              );
            },
          },
          {
            title: "置信度",
            dataIndex: "confidence",
            width: 100,
            render: (value: number) => (
              <Tag color={routeConfidenceColor(value)}>
                {(value * 100).toFixed(0)}%
              </Tag>
            ),
          },
          {
            title: "时间",
            dataIndex: "created_at",
            width: 180,
            render: (value: string) =>
              new Date(value).toLocaleString("zh-CN"),
          },
        ]}
      />
      <Modal
        open={Boolean(editing)}
        title="编辑数字员工路由"
        okText="保存路由"
        confirmLoading={save.isPending}
        okButtonProps={{ disabled: !editing }}
        onOk={() => save.mutate()}
        onCancel={() => setEditing(null)}
      >
        <Form layout="vertical">
          <Form.Item label="数字员工">
            <Text strong>
              {editing ? employeeName(editing.employee_id) : "-"}
            </Text>
          </Form.Item>
          <Form.Item
            label="路由意图"
            extra="使用逗号或换行分隔，例如：退款、投诉、权限变更。"
          >
            <TextArea
              rows={4}
              value={intents}
              onChange={(event) => setIntents(event.target.value)}
            />
          </Form.Item>
          <Space size="middle" align="start">
            <Form.Item label="优先级">
              <InputNumber
                min={0}
                max={1000}
                value={priority}
                onChange={(value) => setPriority(value ?? 100)}
              />
            </Form.Item>
            <Form.Item label="规则状态">
              <Checkbox
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              >
                启用
              </Checkbox>
            </Form.Item>
            <Form.Item label="兜底员工">
              <Checkbox
                checked={fallback}
                onChange={(event) => setFallback(event.target.checked)}
              >
                无匹配时使用
              </Checkbox>
            </Form.Item>
          </Space>
        </Form>
      </Modal>
      </Card>
      <RouteIntentConflictCard />
      <Modal
        open={Boolean(editingEntry)}
        title={`配置员工池 · ${editingEntry?.name ?? ""}`}
        okText="保存员工池"
        confirmLoading={saveEntryEmployees.isPending}
        okButtonProps={{ disabled: entryEmployeeIds.length === 0 }}
        onOk={() => saveEntryEmployees.mutate()}
        onCancel={() => setEditingEntry(null)}
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="员工池决定业务入口可以派给谁"
            description="默认员工和兜底员工保持入口现有配置；其他启用的员工作为专业员工参与意图路由。"
          />
          <Select
            mode="multiple"
            aria-label="选择业务入口数字员工"
            style={{ width: "100%" }}
            value={entryEmployeeIds}
            onChange={setEntryEmployeeIds}
            options={employees
              .filter((employee) =>
                ["ACTIVE", "TRIAL"].includes(employee.status),
              )
              .map((employee) => ({
                value: employee.id,
                label: `${employee.name} · ${
                  employee.status === "ACTIVE" ? "可用" : "试用"
                }`,
              }))}
          />
        </Space>
      </Modal>
    </Space>
  );
}

export function RouteIntentConflictCard() {
  const conflicts = useQuery({
    queryKey: ["digital-employee-route-intent-conflicts"],
    queryFn: listDigitalEmployeeRouteIntentConflicts,
  });
  const data: DigitalEmployeeRouteIntentConflictList | undefined =
    conflicts.data;
  const sourceLabels: Record<string, string> = {
    EXPLICIT: "双方显式配置",
    INHERITED: "双方继承配置",
    MIXED: "显式与继承重叠",
  };

  return (
    <Card
      className="section-card"
      title="意图归属冲突检查"
      loading={conflicts.isLoading}
      extra={
        <Button size="small" onClick={() => conflicts.refetch()}>
          重新检查
        </Button>
      }
    >
      <Paragraph type="secondary">
        显式路由规则优先于岗位模板和员工清单里的继承意图。同一入口员工池中，
        某个词已被另一名员工显式认领时，继承来的同名意图会自动让位；
        双方都显式配置时仍会提示冲突，需要人工决定归属。
      </Paragraph>
      {conflicts.isError && (
        <Alert
          type="error"
          showIcon
          message="意图冲突检查失败"
          description={(conflicts.error as Error).message}
        />
      )}
      {data && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Space wrap size="large">
            <Statistic
              title="参与检查的生效员工"
              value={data.active_employee_count}
            />
            <Statistic title="检查意图词" value={data.checked_terms} />
            <Statistic
              title="显式冲突"
              value={data.conflicts.length}
              valueStyle={{
                color: data.conflicts.length > 0 ? "#cf1322" : "#3f8600",
              }}
            />
            <Statistic
              title="继承意图已让位"
              value={data.suppressed.length}
              valueStyle={{ color: "#d46b08" }}
            />
          </Space>
          {data.conflicts.length === 0 &&
            data.suppressed.length === 0 && (
              <Alert
                type="success"
                showIcon
                message="当前没有意图归属冲突"
                description="同一业务入口的员工池里，每个生效意图词最多只有一名员工负责。"
              />
            )}
          {data.conflicts.length > 0 && (
            <>
              <Title level={5}>需要人工确认的重复意图</Title>
              <Table
                rowKey="term"
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: true }}
                dataSource={data.conflicts}
                columns={[
                  {
                    title: "意图词",
                    dataIndex: "term",
                    width: 140,
                    render: (value: string) => (
                      <Tag color="red">{value}</Tag>
                    ),
                  },
                  {
                    title: "同时认领的员工",
                    dataIndex: "employee_names",
                    render: (value: string[]) => (
                      <Space wrap size={4}>
                        {value.map((name) => (
                          <Tag key={name}>{name}</Tag>
                        ))}
                      </Space>
                    ),
                  },
                  {
                    title: "共同业务入口",
                    dataIndex: "entry_names",
                    render: (value: string[]) => value.join("、"),
                  },
                  {
                    title: "冲突来源",
                    dataIndex: "source",
                    width: 140,
                    render: (value: string) => (
                      <Tag color="orange">
                        {sourceLabels[value] ?? value}
                      </Tag>
                    ),
                  },
                ]}
              />
            </>
          )}
          {data.suppressed.length > 0 && (
            <>
              <Title level={5}>已自动让位的继承意图</Title>
              <Table
                rowKey="term"
                size="small"
                pagination={{ pageSize: 10, showSizeChanger: true }}
                dataSource={data.suppressed}
                columns={[
                  {
                    title: "意图词",
                    dataIndex: "term",
                    width: 140,
                    render: (value: string) => (
                      <Tag color="gold">{value}</Tag>
                    ),
                  },
                  {
                    title: "让位员工（继承来源）",
                    dataIndex: "affected_employee_names",
                    render: (value: string[]) => value.join("、"),
                  },
                  {
                    title: "归属员工（显式规则）",
                    dataIndex: "owner_employee_names",
                    render: (value: string[]) => (
                      <Space wrap size={4}>
                        {value.map((name) => (
                          <Tag color="green" key={name}>
                            {name}
                          </Tag>
                        ))}
                      </Space>
                    ),
                  },
                  {
                    title: "共同业务入口",
                    dataIndex: "entry_names",
                    render: (value: string[]) => value.join("、"),
                  },
                ]}
              />
            </>
          )}
        </Space>
      )}
    </Card>
  );
}

export function RouteEvaluationCard({
  employees,
  entries,
}: {
  employees: DigitalEmployee[];
  entries: BusinessServiceEntry[];
}) {
  const [entryId, setEntryId] = useState("");
  const [dataset, setDataset] =
    useState<DigitalEmployeeRouteEvaluationDataset>("TUNING");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCase, setEditingCase] =
    useState<DigitalEmployeeRouteEvaluationCase | null>(null);
  const [question, setQuestion] = useState("");
  const [notes, setNotes] = useState("");
  const [expectedEmployeeId, setExpectedEmployeeId] = useState("");
  const [caseDataset, setCaseDataset] =
    useState<DigitalEmployeeRouteEvaluationDataset>("TUNING");
  const [caseEnabled, setCaseEnabled] = useState(true);
  const [failuresOnly, setFailuresOnly] = useState(false);

  useEffect(() => {
    if (entryId || entries.length === 0) return;
    const preferred =
      entries.find((entry) => entry.code === "enterprise_service_desk") ??
      entries[0];
    setEntryId(preferred.id);
  }, [entries, entryId]);

  const entry = entries.find((item) => item.id === entryId);
  const poolIds = new Set(
    (entry?.employees ?? [])
      .filter((employee) => employee.enabled)
      .map((employee) => employee.employee_id),
  );
  const expectedEmployees = employees.filter(
    (employee) =>
      poolIds.has(employee.id) &&
      employee.status === "ACTIVE" &&
      employee.business_unit_id === entry?.business_unit_id,
  );
  const {
    cases,
    runs,
    selectedRun,
    setSelectedRunId,
    saveCase,
    removeCase,
    runEvaluation,
  } = useRouteEvaluation({ entryId, dataset });
  const openCreate = () => {
    setEditingCase(null);
    setQuestion("");
    setNotes("");
    setCaseDataset(dataset);
    setCaseEnabled(true);
    setExpectedEmployeeId(
      expectedEmployees.find(
        (employee) => employee.id === entry?.default_employee_id,
      )?.id ??
        expectedEmployees[0]?.id ??
        "",
    );
    setModalOpen(true);
  };
  const openEdit = (item: DigitalEmployeeRouteEvaluationCase) => {
    setEditingCase(item);
    setQuestion(item.question);
    setNotes(item.notes);
    setCaseDataset(item.dataset);
    setCaseEnabled(item.enabled);
    setExpectedEmployeeId(item.expected_employee_id);
    setModalOpen(true);
  };
  const accuracyRate = accuracyPercent(selectedRun);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        className="section-card"
        title="路由评测集"
        loading={runs.isLoading && Boolean(entryId)}
        extra={
          <Space wrap>
            <Select
              aria-label="评测业务入口"
              value={entryId || undefined}
              onChange={(value) => {
                setEntryId(value);
                setSelectedRunId("");
              }}
              placeholder="选择业务入口"
              style={{ width: 240 }}
              options={entries.map((item) => ({
                value: item.id,
                label: `${item.name} · ${item.employees.length} 名员工`,
              }))}
            />
            <Select
              aria-label="评测数据集"
              value={dataset}
              onChange={(value: DigitalEmployeeRouteEvaluationDataset) => {
                setDataset(value);
                setSelectedRunId("");
                setFailuresOnly(false);
              }}
              style={{ width: 130 }}
              options={[
                { value: "TUNING", label: routeEvaluationDatasetLabels.TUNING },
                { value: "HOLDOUT", label: routeEvaluationDatasetLabels.HOLDOUT },
              ]}
            />
            <Button
              type="primary"
              loading={runEvaluation.isPending}
              disabled={!entryId || (cases.data?.length ?? 0) === 0}
              onClick={() => runEvaluation.mutate()}
            >
              运行评测
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary">
          每条问题都固定期望员工。运行时会复用真实路由逻辑，但不会写入最近路由记录，
          因此可以反复回归。调参集用于调整意图和员工池，留出集只用来验收：
          不要根据留出集的失败问题去改规则，否则它也会失去参考价值。
        </Paragraph>
        <div
          style={{
            display: "grid",
            gap: 12,
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            marginBottom: 16,
          }}
        >
          <Card size="small">
            <Statistic
              title="启用的问题"
              value={enabledCaseCount(cases.data)}
              suffix={`/ ${cases.data?.length ?? 0}`}
            />
          </Card>
          <Card size="small">
            <Statistic
              title="最近准确率"
              value={accuracyRate}
              suffix="%"
              valueStyle={{
                color:
                  accuracyRate >= 90
                    ? "#3f8600"
                    : accuracyRate >= 75
                      ? "#d46b08"
                      : "#cf1322",
              }}
            />
          </Card>
          <Card size="small">
            <Statistic
              title="最近命中"
              value={selectedRun?.passed ?? 0}
              suffix={`/ ${selectedRun?.total ?? 0}`}
            />
          </Card>
          <Card size="small">
            <Statistic
              title="历史评测"
              value={runs.data?.total ?? 0}
              suffix="次"
            />
          </Card>
        </div>
        {selectedRun ? (
          <Alert
            type={
              selectedRun.failed === 0
                ? "success"
                : selectedRun.accuracy >= 0.75
                  ? "warning"
                  : "error"
            }
            showIcon
            message={`最近一次评测（${
              routeEvaluationDatasetLabels[selectedRun.dataset]
            }）：${selectedRun.passed}/${selectedRun.total} 命中`}
            description={`准确率 ${(selectedRun.accuracy * 100).toFixed(1)}%，由 ${
              selectedRun.created_by
            } 于 ${new Date(selectedRun.created_at).toLocaleString(
              "zh-CN",
            )} 运行。`}
          />
        ) : (
          <Alert
            type="info"
            showIcon
            message={`${routeEvaluationDatasetLabels[dataset]}还没有评测记录`}
            description="添加 10–20 条贴近真实提问的问题，然后运行一次评测建立基线。"
          />
        )}
      </Card>

      {selectedRun && selectedRun.failure_analysis.failed_total > 0 && (
        <Card
          className="section-card"
          title="失败分析"
          extra={
            <Tag color="red">
              {selectedRun.failure_analysis.failed_total} 条误派
            </Tag>
          }
        >
          <div
            style={{
              display: "grid",
              gap: 12,
              gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
              marginBottom: 16,
            }}
          >
            <Card size="small">
              <Statistic
                title="落在外池"
                value={selectedRun.failure_analysis.out_of_pool_total}
                suffix={`/ ${selectedRun.failure_analysis.failed_total}`}
              />
            </Card>
            <Card size="small">
              <Statistic
                title="主要失败类型"
                value={
                  routeReasonLabels[
                    selectedRun.failure_analysis.reasons[0]?.reason_code ?? ""
                  ] ??
                  selectedRun.failure_analysis.reasons[0]?.reason_code ??
                  "暂无"
                }
                valueStyle={{ fontSize: 18 }}
              />
            </Card>
          </div>
          <Paragraph type="secondary">
            落在外池表示路由结果不在当前业务入口的员工池内。这类问题在真实流量中会
            绕开该入口，需要优先检查入口绑定和路由规则。
          </Paragraph>
          <Table
            rowKey={(row) =>
              `${row.expected_employee_name}-${row.predicted_employee_name}`
            }
            size="small"
            pagination={false}
            dataSource={selectedRun.failure_analysis.confusions}
            style={{ marginBottom: 16 }}
            columns={[
              {
                title: "期望员工",
                dataIndex: "expected_employee_name",
                width: 180,
              },
              {
                title: "实际派给",
                dataIndex: "predicted_employee_name",
                width: 180,
              },
              { title: "次数", dataIndex: "count", width: 80 },
              {
                title: "其中池外",
                dataIndex: "out_of_pool_count",
                width: 100,
              },
            ]}
          />
          <Table
            rowKey="reason_code"
            size="small"
            pagination={false}
            dataSource={selectedRun.failure_analysis.reasons}
            columns={[
              {
                title: "判断方式",
                dataIndex: "reason_code",
                render: (value: string) => routeReasonLabels[value] ?? value,
              },
              { title: "次数", dataIndex: "count", width: 120 },
            ]}
          />
        </Card>
      )}

      <Card
        className="section-card"
        title="评测问题"
        extra={
          <Button onClick={openCreate} disabled={!entryId}>
            添加问题
          </Button>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={cases.isLoading}
          dataSource={cases.data ?? []}
          pagination={{ pageSize: 12, showSizeChanger: true }}
          columns={[
            {
              title: "问题",
              dataIndex: "question",
              render: (value: string, item) => (
                <Space direction="vertical" size={0}>
                  <Text>{value}</Text>
                  {item.notes && (
                    <Text type="secondary">{item.notes}</Text>
                  )}
                </Space>
              ),
            },
            {
              title: "期望员工",
              dataIndex: "expected_employee_name",
              width: 180,
            },
            {
              title: "启用",
              dataIndex: "enabled",
              width: 80,
              render: (value: boolean) => (
                <Tag color={value ? "green" : "default"}>
                  {value ? "参与" : "暂停"}
                </Tag>
              ),
            },
            {
              title: "操作",
              width: 140,
              render: (_value, item) => (
                <Space size={4}>
                  <Button type="link" onClick={() => openEdit(item)}>
                    编辑
                  </Button>
                  <Button
                    type="link"
                    danger
                    onClick={() =>
                      Modal.confirm({
                        title: "删除这条评测问题？",
                        content: item.question,
                        okText: "删除",
                        cancelText: "取消",
                        onOk: () => removeCase.mutateAsync(item.id),
                      })
                    }
                  >
                    删除
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      {selectedRun && (
        <Card
          className="section-card"
          title={`最近评测结果 · ${
            routeEvaluationDatasetLabels[selectedRun.dataset]
          }`}
          extra={
            <Checkbox
              checked={failuresOnly}
              onChange={(event) => setFailuresOnly(event.target.checked)}
            >
              只看误派
            </Checkbox>
          }
        >
          <Table
            rowKey="case_id"
            size="small"
            dataSource={filterEvaluationResults(
              selectedRun.results,
              failuresOnly,
            )}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            expandable={{
              expandedRowRender: (row) => (
                <RouteEvidence candidates={row.candidates} />
              ),
              rowExpandable: (row) => row.candidates.length > 0,
            }}
            columns={[
              { title: "问题", dataIndex: "question" },
              {
                title: "期望员工",
                dataIndex: "expected_employee_name",
                width: 170,
              },
              {
                title: "实际员工",
                dataIndex: "predicted_employee_name",
                width: 190,
                render: (value: string, row) => (
                  <Space size={4} wrap>
                    <Tag color={row.matched ? "green" : "red"}>{value}</Tag>
                    {!row.predicted_in_pool && (
                      <Tag color="volcano">池外</Tag>
                    )}
                  </Space>
                ),
              },
              {
                title: "结果",
                dataIndex: "matched",
                width: 90,
                render: (value: boolean) =>
                  value ? (
                    <Tag color="green">命中</Tag>
                  ) : (
                    <Tag color="red">误派</Tag>
                  ),
              },
              {
                title: "判断方式",
                dataIndex: "reason_code",
                width: 160,
                render: (value: string) =>
                  routeReasonLabels[value] ?? value,
              },
              {
                title: "置信度",
                dataIndex: "confidence",
                width: 100,
                render: (value: number) => (
                  <Tag color={routeConfidenceColor(value)}>
                    {(value * 100).toFixed(0)}%
                  </Tag>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Card
        className="section-card"
        title={`历史评测 · ${routeEvaluationDatasetLabels[dataset]}`}
      >
        <Table
          rowKey="id"
          size="small"
          loading={runs.isLoading}
          dataSource={runs.data?.items ?? []}
          pagination={{ pageSize: 10, showSizeChanger: true }}
          columns={[
            {
              title: "运行时间",
              dataIndex: "created_at",
              render: (value: string) =>
                new Date(value).toLocaleString("zh-CN"),
            },
            {
              title: "准确率",
              dataIndex: "accuracy",
              width: 110,
              render: (value: number) => (
                <Tag
                  color={
                    value >= 0.9 ? "green" : value >= 0.75 ? "gold" : "red"
                  }
                >
                  {(value * 100).toFixed(0)}%
                </Tag>
              ),
            },
            {
              title: "命中 / 总数",
              width: 130,
              render: (_value, row) => `${row.passed} / ${row.total}`,
            },
            { title: "运行人", dataIndex: "created_by", width: 180 },
            {
              title: "操作",
              width: 100,
              render: (_value, row) => (
                <Button
                  type="link"
                  onClick={() => setSelectedRunId(row.id)}
                >
                  查看结果
                </Button>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={modalOpen}
        title={editingCase ? "编辑评测问题" : "添加评测问题"}
        okText={editingCase ? "保存问题" : "添加问题"}
        confirmLoading={saveCase.isPending}
        onOk={() =>
          saveCase.mutate(
            {
              caseId: editingCase?.id ?? null,
              values: {
                expectedEmployeeId,
                dataset: caseDataset,
                question,
                notes,
                enabled: caseEnabled,
              },
            },
            {
              onSuccess: () => {
                setModalOpen(false);
                setEditingCase(null);
              },
            },
          )
        }
        onCancel={() => {
          setModalOpen(false);
          setEditingCase(null);
        }}
      >
        <Form layout="vertical">
          <Form.Item label="业务入口">
            <Text strong>{entry?.name ?? "未选择"}</Text>
          </Form.Item>
          <Form.Item
            label="所属评测集"
            extra="留出集只用于验收，不要根据这里的问题去调整路由规则。"
          >
            <Select
              aria-label="所属评测集"
              value={caseDataset}
              onChange={setCaseDataset}
              options={[
                { value: "TUNING", label: routeEvaluationDatasetLabels.TUNING },
                { value: "HOLDOUT", label: routeEvaluationDatasetLabels.HOLDOUT },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="评测问题"
            extra="用员工真实会问的说法，例如：办公室 VPN 连不上怎么办？"
          >
            <TextArea
              aria-label="评测问题"
              rows={3}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="应处理员工">
            <Select
              aria-label="应处理员工"
              value={expectedEmployeeId || undefined}
              onChange={setExpectedEmployeeId}
              placeholder="选择员工池中的在岗员工"
              options={expectedEmployees.map((employee) => ({
                value: employee.id,
                label: employee.name,
              }))}
            />
          </Form.Item>
          <Form.Item label="备注（可选）">
            <Input
              aria-label="评测备注"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="例如：财务与费用"
            />
          </Form.Item>
          <Form.Item>
            <Checkbox
              checked={caseEnabled}
              onChange={(event) => setCaseEnabled(event.target.checked)}
            >
              参与评测
            </Checkbox>
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  );
}
