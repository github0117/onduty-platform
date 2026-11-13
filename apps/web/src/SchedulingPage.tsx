import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { ApiError } from "./api";
import {
  cloneSchedulingRoster,
  createSchedulingShift,
  getOrCreateSchedulingRoster,
  getSchedulingOnDuty,
  getSchedulingPolicy,
  listCustomerAgentPresence,
  listSchedulingRosters,
  listSchedulingShifts,
  publishSchedulingRoster,
  saveSchedulingRosterDraft,
  updateSchedulingPolicy,
  updateSchedulingShift,
} from "./api";
import { useAuth } from "./auth";
import { message } from "./feedback";
import type {
  OnDutyAgent,
  Roster,
  RosterEntry,
  ShiftTemplate,
} from "./types";

const { Paragraph, Text, Title } = Typography;

const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = `${value.getMonth() + 1}`.padStart(2, "0");
  const day = `${value.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function mondayOf(value: Date): Date {
  const result = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const offset = (result.getDay() + 6) % 7;
  result.setDate(result.getDate() - offset);
  return result;
}

function addDays(isoDate: string, days: number): string {
  const value = new Date(`${isoDate}T00:00:00`);
  value.setDate(value.getDate() + days);
  return toIsoDate(value);
}

function weekDates(weekStart: string): string[] {
  return Array.from({ length: 7 }, (_, index) => addDays(weekStart, index));
}

function cellKey(agentId: string, shiftDate: string): string {
  return `${agentId}|${shiftDate}`;
}

function shiftLabel(shift: ShiftTemplate): string {
  return `${shift.name} ${shift.start_local.slice(0, 5)}-${shift.end_local.slice(0, 5)}${shift.cross_day ? " 跨天" : ""}`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

interface ShiftDraft {
  name: string;
  start_local: string;
  end_local: string;
}

const emptyShiftDraft: ShiftDraft = {
  name: "",
  start_local: "09:00",
  end_local: "18:00",
};

export default function SchedulingPage() {
  const queryClient = useQueryClient();
  const { activeBusinessUnitLabel } = useAuth();
  const [weekStart, setWeekStart] = useState(() => toIsoDate(mondayOf(new Date())));
  const [cellValues, setCellValues] = useState<Record<string, string>>({});
  const [shiftModalOpen, setShiftModalOpen] = useState(false);
  const [editingShift, setEditingShift] = useState<ShiftTemplate | null>(null);
  const [shiftDraft, setShiftDraft] = useState<ShiftDraft>(emptyShiftDraft);

  const shiftsQuery = useQuery({
    queryKey: ["scheduling-shifts"],
    queryFn: listSchedulingShifts,
  });
  const rostersQuery = useQuery({
    queryKey: ["scheduling-rosters", weekStart],
    queryFn: () => listSchedulingRosters(weekStart),
  });
  const presenceQuery = useQuery({
    queryKey: ["customer-agent-presence"],
    queryFn: listCustomerAgentPresence,
  });
  const policyQuery = useQuery({
    queryKey: ["scheduling-policy"],
    queryFn: getSchedulingPolicy,
  });
  const onDutyQuery = useQuery({
    queryKey: ["scheduling-on-duty"],
    queryFn: getSchedulingOnDuty,
  });

  const draft = useMemo<Roster | undefined>(
    () => rostersQuery.data?.items.find((item) => item.status === "DRAFT"),
    [rostersQuery.data],
  );
  const published = useMemo<Roster | undefined>(
    () => rostersQuery.data?.items.find((item) => item.status === "PUBLISHED"),
    [rostersQuery.data],
  );
  const archived = useMemo<Roster[]>(
    () =>
      (rostersQuery.data?.items ?? []).filter(
        (item) => item.status === "ARCHIVED",
      ),
    [rostersQuery.data],
  );

  const activeShifts = useMemo(
    () => (shiftsQuery.data?.items ?? []).filter((item) => item.status === "ACTIVE"),
    [shiftsQuery.data],
  );
  const shiftById = useMemo(() => {
    const map = new Map<string, ShiftTemplate>();
    for (const item of shiftsQuery.data?.items ?? []) map.set(item.id, item);
    return map;
  }, [shiftsQuery.data]);

  const currentEntries = draft?.entries ?? published?.entries ?? [];

  useEffect(() => {
    const source = draft ?? published;
    const next: Record<string, string> = {};
    for (const entry of source?.entries ?? []) {
      if (entry.shift_template_id) {
        next[cellKey(entry.agent_id, entry.shift_date)] = entry.shift_template_id;
      }
    }
    setCellValues(next);
  }, [draft?.id, draft?.version, published?.id]);

  const entryValue = (agentId: string, shiftDate: string): string | undefined =>
    cellValues[cellKey(agentId, shiftDate)];

  const agentRows = useMemo(() => {
    const map = new Map<string, { agent_id: string; display_name: string }>();
    for (const presence of presenceQuery.data?.items ?? []) {
      map.set(presence.agent_id, {
        agent_id: presence.agent_id,
        display_name: presence.display_name,
      });
    }
    for (const entry of currentEntries) {
      if (!map.has(entry.agent_id)) {
        map.set(entry.agent_id, {
          agent_id: entry.agent_id,
          display_name: entry.agent_display_name,
        });
      }
    }
    return [...map.values()].sort((left, right) =>
      left.display_name.localeCompare(right.display_name, "zh-CN"),
    );
  }, [presenceQuery.data, currentEntries]);

  const invalidateScheduling = () => {
    void queryClient.invalidateQueries({ queryKey: ["scheduling-rosters"] });
    void queryClient.invalidateQueries({ queryKey: ["scheduling-shifts"] });
    void queryClient.invalidateQueries({ queryKey: ["scheduling-policy"] });
    void queryClient.invalidateQueries({ queryKey: ["scheduling-on-duty"] });
    void queryClient.invalidateQueries({ queryKey: ["customer-agent-presence"] });
    void queryClient.invalidateQueries({ queryKey: ["customer-assignment-queue"] });
    void queryClient.invalidateQueries({ queryKey: ["customer-service-metrics"] });
  };

  const createDraftMutation = useMutation({
    mutationFn: () => getOrCreateSchedulingRoster(weekStart),
    onSuccess: () => {
      message.success("已创建本周草稿");
      invalidateScheduling();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const saveDraftMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("当前没有可保存的草稿");
      const entries = Object.entries(cellValues)
        .filter(([, shiftTemplateId]) => Boolean(shiftTemplateId))
        .map(([key, shiftTemplateId]) => {
          const [agentId, shiftDate] = key.split("|");
          return {
            agent_id: agentId,
            shift_date: shiftDate,
            shift_template_id: shiftTemplateId,
          };
        });
      return saveSchedulingRosterDraft(draft.id, draft.version, entries);
    },
    onSuccess: (roster) => {
      message.success(`草稿已保存（版本 ${roster.version}）`);
      invalidateScheduling();
    },
    onError: (error: Error) => {
      message.error(error.message);
      if (error instanceof ApiError && error.code === "ROSTER_VERSION_CONFLICT") {
        void rostersQuery.refetch();
      }
    },
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("当前没有可发布的草稿");
      return publishSchedulingRoster(draft.id);
    },
    onSuccess: () => {
      message.success("班表已发布，当前周版本已替换");
      invalidateScheduling();
    },
    onError: (error: Error) => {
      message.error(error.message);
      if (error instanceof ApiError && error.code === "INVALID_ROSTER_STATE") {
        void rostersQuery.refetch();
      }
    },
  });

  const cloneMutation = useMutation({
    mutationFn: async () => {
      const source = published ?? archived[0];
      if (!source) throw new Error("暂无可克隆的发布或归档版本");
      return cloneSchedulingRoster(source.id);
    },
    onSuccess: () => {
      message.success("已从历史版本克隆本周草稿");
      invalidateScheduling();
    },
    onError: (error: Error) => {
      message.error(error.message);
      void rostersQuery.refetch();
    },
  });

  const policyMutation = useMutation({
    mutationFn: (enabled: boolean) => updateSchedulingPolicy(enabled),
    onSuccess: (policy) => {
      message.success(
        policy.enforce_published_schedule
          ? "已开启按班表约束自动分配"
          : "已关闭约束，恢复原有自动分配规则",
      );
      invalidateScheduling();
    },
    onError: (error: Error) => {
      message.error(error.message);
      void policyQuery.refetch();
    },
  });

  const createShiftMutation = useMutation({
    mutationFn: () => createSchedulingShift(shiftDraft),
    onSuccess: () => {
      message.success("班次已创建");
      setShiftModalOpen(false);
      setShiftDraft(emptyShiftDraft);
      invalidateScheduling();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const updateShiftMutation = useMutation({
    mutationFn: (shift: ShiftTemplate) =>
      updateSchedulingShift(shift.id, {
        name: shiftDraft.name,
        start_local: shiftDraft.start_local,
        end_local: shiftDraft.end_local,
        version: shift.version,
      }),
    onSuccess: () => {
      message.success("班次已更新");
      setShiftModalOpen(false);
      setEditingShift(null);
      setShiftDraft(emptyShiftDraft);
      invalidateScheduling();
    },
    onError: (error: Error) => {
      message.error(error.message);
      if (error instanceof ApiError && error.code === "SHIFT_VERSION_CONFLICT") {
        void shiftsQuery.refetch();
      }
    },
  });

  const archiveShiftMutation = useMutation({
    mutationFn: (shift: ShiftTemplate) =>
      updateSchedulingShift(shift.id, {
        status: "ARCHIVED",
        version: shift.version,
      }),
    onSuccess: () => {
      message.success("班次已停用，历史班表快照保持不变");
      invalidateScheduling();
    },
    onError: (error: Error) => message.error(error.message),
  });

  const submitShift = () => {
    if (!TIME_PATTERN.test(shiftDraft.start_local) || !TIME_PATTERN.test(shiftDraft.end_local)) {
      message.warning("时间格式应为 HH:MM，例如 09:00");
      return;
    }
    if (!shiftDraft.name.trim()) {
      message.warning("请填写班次名称");
      return;
    }
    if (shiftDraft.start_local === shiftDraft.end_local) {
      message.warning("起止时间不能相同；夜班请让结束时间早于开始时间");
      return;
    }
    if (editingShift) {
      updateShiftMutation.mutate(editingShift);
    } else {
      createShiftMutation.mutate();
    }
  };

  const shiftColumns: ColumnsType<ShiftTemplate> = [
    {
      title: "班次",
      dataIndex: "name",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.start_local.slice(0, 5)} - {record.end_local.slice(0, 5)}
            {record.cross_day ? " · 次日结束" : ""}
          </Text>
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={value === "ACTIVE" ? "green" : "default"}>
          {value === "ACTIVE" ? "启用" : "已停用"}
        </Tag>
      ),
    },
    { title: "版本", dataIndex: "version", width: 80 },
    {
      title: "操作",
      width: 170,
      render: (_value, record) => (
        <Space>
          <Button
            size="small"
            onClick={() => {
              setEditingShift(record);
              setShiftDraft({
                name: record.name,
                start_local: record.start_local.slice(0, 5),
                end_local: record.end_local.slice(0, 5),
              });
              setShiftModalOpen(true);
            }}
          >
            编辑
          </Button>
          {record.status === "ACTIVE" && (
            <Popconfirm
              title="停用该班次？"
              description="已发布班表保留快照，不受影响；草稿引用时会被拒绝。"
              onConfirm={() => archiveShiftMutation.mutate(record)}
            >
              <Button
                size="small"
                danger
                loading={
                  archiveShiftMutation.isPending &&
                  archiveShiftMutation.variables?.id === record.id
                }
              >
                停用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  const dateColumns: ColumnsType<{ agent_id: string; display_name: string }> =
    weekDates(weekStart).map((shiftDate) => ({
      title: `${shiftDate.slice(5)} ${["一", "二", "三", "四", "五", "六", "日"][new Date(`${shiftDate}T00:00:00`).getDay() === 0 ? 6 : new Date(`${shiftDate}T00:00:00`).getDay() - 1]}`,
      key: shiftDate,
      width: 140,
      render: (_value, record) => {
        const current = entryValue(record.agent_id, shiftDate);
        const currentShift = current ? shiftById.get(current) : undefined;
        const options = activeShifts.map((shift) => ({
          value: shift.id,
          label: shiftLabel(shift),
        }));
        if (current && !currentShift) {
          options.unshift({ value: current, label: "历史班次（已停用）" });
        }
        return (
          <Select
            size="small"
            allowClear
            style={{ width: "100%" }}
            placeholder="未排班"
            value={current}
            disabled={!draft || saveDraftMutation.isPending}
            onChange={(value?: string) =>
              setCellValues((previous) => {
                const next = { ...previous };
                const key = cellKey(record.agent_id, shiftDate);
                if (value) next[key] = value;
                else delete next[key];
                return next;
              })
            }
            options={options}
          />
        );
      },
    }));

  const gridColumns: ColumnsType<{ agent_id: string; display_name: string }> = [
    {
      title: "坐席",
      dataIndex: "display_name",
      fixed: "left",
      width: 160,
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.agent_id}
          </Text>
        </Space>
      ),
    },
    ...dateColumns,
  ];

  const onDutyColumns: ColumnsType<OnDutyAgent> = [
    {
      title: "坐席",
      dataIndex: "display_name",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{value}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {record.agent_id}
          </Text>
        </Space>
      ),
    },
    {
      title: "在线",
      dataIndex: "online",
      width: 90,
      render: (value: boolean) => (
        <Tag color={value ? "green" : "default"}>{value ? "在线" : "离线"}</Tag>
      ),
    },
    {
      title: "当班",
      dataIndex: "on_shift",
      width: 100,
      render: (value: boolean) => (
        <Tag color={value ? "green" : "orange"}>{value ? "当班" : "未当班"}</Tag>
      ),
    },
    {
      title: "班次时间",
      key: "window",
      render: (_value, record) =>
        record.shift_start_at && record.shift_end_at
          ? `${formatTime(record.shift_start_at)} - ${formatTime(record.shift_end_at)}`
          : "-",
    },
    {
      title: "不可派原因",
      dataIndex: "excluded_reasons",
      render: (value: string[]) =>
        value.length === 0 ? (
          <Text type="success">可参与自动分配</Text>
        ) : (
          <Space size={4} wrap>
            {value.map((reason) => (
              <Tag key={reason} color="volcano">
                {reason}
              </Tag>
            ))}
          </Space>
        ),
    },
  ];

  const policy = policyQuery.data;
  const onDuty = onDutyQuery.data;
  const firstScreenError =
    rostersQuery.error ?? shiftsQuery.error ?? policyQuery.error;

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space align="center" wrap style={{ justifyContent: "space-between", width: "100%" }}>
            <Space direction="vertical" size={0}>
              <Title level={4} style={{ margin: 0 }}>
                智能排班 · {activeBusinessUnitLabel}
              </Title>
              <Text type="secondary">
                班表只约束自动分配；下班不回收进行中会话，手工分配和接管不受影响。
              </Text>
            </Space>
            <Space wrap>
              <Button onClick={() => setWeekStart(addDays(weekStart, -7))}>
                上一周
              </Button>
              <Tag color="blue">{weekStart} ~ {addDays(weekStart, 6)}</Tag>
              <Button onClick={() => setWeekStart(addDays(weekStart, 7))}>
                下一周
              </Button>
              <Button onClick={() => setWeekStart(toIsoDate(mondayOf(new Date())))}>
                本周
              </Button>
            </Space>
          </Space>
          <Space wrap>
            <Text>时区：{draft?.timezone ?? published?.timezone ?? "Asia/Shanghai"}</Text>
            {published ? (
              <Tag color="green">已发布 v{published.version}</Tag>
            ) : (
              <Tag>本周尚未发布</Tag>
            )}
            {draft ? (
              <Tag color="gold">草稿 v{draft.version}</Tag>
            ) : (
              <Tag>无草稿</Tag>
            )}
            {archived.length > 0 && <Tag>历史版本 {archived.length}</Tag>}
          </Space>
        </Space>
      </Card>

      {firstScreenError && (
        <Alert
          type="error"
          showIcon
          message="排班数据加载失败"
          description={firstScreenError.message}
          action={
            <Button
              size="small"
              onClick={() => {
                void rostersQuery.refetch();
                void shiftsQuery.refetch();
                void policyQuery.refetch();
              }}
            >
              重试
            </Button>
          }
        />
      )}

      <Card title="按班表约束自动分配">
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <Space wrap>
            <Switch
              checked={policy?.enforce_published_schedule ?? false}
              loading={policyMutation.isPending}
              disabled={!policy || policyMutation.isPending}
              onChange={(checked) => policyMutation.mutate(checked)}
            />
            <Text strong>
              {policy?.enforce_published_schedule
                ? "已开启：自动分配只选择当前班次内的坐席"
                : "已关闭：沿用在线、技能、风险和负载规则"}
            </Text>
            {!policy?.persisted && <Tag>数据库无策略行，默认关闭</Tag>}
          </Space>
          {policy?.enforce_published_schedule && policy.coverage_gap && (
            <Alert
              type="warning"
              showIcon
              message="当前周没有已发布班表，自动分配会持续等待"
              description="已开启约束后系统不会自动回退旧规则。请发布当前周班表，或关闭该开关。"
            />
          )}
          {!policy?.enforce_published_schedule && (
            <Text type="secondary">
              开启前必须先发布覆盖当前周的班表；关闭后立即恢复原有自动分配规则。
            </Text>
          )}
        </Space>
      </Card>

      <Card
        title="周班表"
        extra={
          <Space wrap>
            {!draft && !published && (
              <Button
                type="primary"
                loading={createDraftMutation.isPending}
                onClick={() => createDraftMutation.mutate()}
              >
                创建本周草稿
              </Button>
            )}
            {!draft && (published || archived.length > 0) && (
              <Button loading={cloneMutation.isPending} onClick={() => cloneMutation.mutate()}>
                从历史版本克隆修订
              </Button>
            )}
            {draft && (
              <>
                <Button
                  loading={saveDraftMutation.isPending}
                  disabled={saveDraftMutation.isPending || publishMutation.isPending}
                  onClick={() => saveDraftMutation.mutate()}
                >
                  保存草稿
                </Button>
                <Popconfirm
                  title="发布本周班表？"
                  description="发布后当前周已有的发布版本会被归档，草稿快照不可再修改。"
                  onConfirm={() => publishMutation.mutate()}
                  disabled={draft.entries.length === 0}
                >
                  <Button
                    type="primary"
                    loading={publishMutation.isPending}
                    disabled={draft.entries.length === 0 || saveDraftMutation.isPending}
                  >
                    发布班表
                  </Button>
                </Popconfirm>
              </>
            )}
          </Space>
        }
      >
        {agentRows.length === 0 ? (
          <Empty description="当前业务单元的坐席目录为空。坐席先在工作台心跳上线后才会出现在这里。" />
        ) : (
          <Table
            rowKey="agent_id"
            size="small"
            pagination={false}
            columns={gridColumns}
            dataSource={agentRows}
            scroll={{ x: 1200 }}
            locale={{
              emptyText: draft
                ? "从单元格选择班次后保存草稿"
                : "本周还没有可编辑草稿",
            }}
          />
        )}
        {!draft && published && (
          <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            已发布班表不可直接修改。需要调整时请先克隆修订，再保存并发布新版本。
          </Paragraph>
        )}
      </Card>

      <Card title="当前当班坐席">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {onDuty && onDuty.coverage_gap && (
            <Alert
              type="warning"
              showIcon
              message="覆盖缺口：本周没有已发布班表"
              description="若已开启按班表约束，自动分配不会选中任何坐席，待分配会话会继续排队。"
            />
          )}
          <Text type="secondary">
            查询时间：{onDuty ? formatTime(onDuty.now) : "-"} · 约束状态：
            {onDuty?.schedule_enforced ? "已开启" : "已关闭"}
          </Text>
          <Table
            rowKey="agent_id"
            size="small"
            pagination={false}
            columns={onDutyColumns}
            dataSource={onDuty?.items ?? []}
            locale={{ emptyText: "当前业务单元还没有坐席记录" }}
          />
        </Space>
      </Card>

      <Card
        title="班次模板"
        extra={
          <Button
            onClick={() => {
              setEditingShift(null);
              setShiftDraft(emptyShiftDraft);
              setShiftModalOpen(true);
            }}
          >
            新增班次
          </Button>
        }
      >
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          columns={shiftColumns}
          dataSource={shiftsQuery.data?.items ?? []}
          locale={{ emptyText: "还没有班次模板，先新增一个白班或夜班" }}
        />
      </Card>

      <Modal
        title={editingShift ? "编辑班次" : "新增班次"}
        open={shiftModalOpen}
        okText={editingShift ? "保存" : "创建"}
        confirmLoading={
          createShiftMutation.isPending || updateShiftMutation.isPending
        }
        onOk={submitShift}
        onCancel={() => {
          setShiftModalOpen(false);
          setEditingShift(null);
          setShiftDraft(emptyShiftDraft);
        }}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Input
            placeholder="班次名称，例如 白班 / 夜班"
            value={shiftDraft.name}
            maxLength={100}
            onChange={(event) =>
              setShiftDraft((previous) => ({ ...previous, name: event.target.value }))
            }
          />
          <Space>
            <Input
              addonBefore="开始"
              placeholder="09:00"
              value={shiftDraft.start_local}
              maxLength={5}
              onChange={(event) =>
                setShiftDraft((previous) => ({
                  ...previous,
                  start_local: event.target.value,
                }))
              }
            />
            <Input
              addonBefore="结束"
              placeholder="18:00"
              value={shiftDraft.end_local}
              maxLength={5}
              onChange={(event) =>
                setShiftDraft((previous) => ({
                  ...previous,
                  end_local: event.target.value,
                }))
              }
            />
          </Space>
          <Text type="secondary">
            结束时间早于开始时间表示跨天班；起止相同会被拒绝。时区沿用班表时区。
          </Text>
        </Space>
      </Modal>

      {published && (
        <Card size="small" title="发布版本">
          <Space wrap>
            <Text>
              发布于 {formatTime(published.published_at)} · 版本 {published.version} · 条目{" "}
              {published.entries.length}
            </Text>
            <Button
              size="small"
              loading={cloneMutation.isPending}
              disabled={Boolean(draft)}
              onClick={() => cloneMutation.mutate()}
            >
              {draft ? "已有草稿，先保存或删除后再克隆" : "克隆为修订草稿"}
            </Button>
          </Space>
        </Card>
      )}

      {entrySummary(currentEntries)}
    </Space>
  );
}

function entrySummary(entries: RosterEntry[]) {
  if (entries.length === 0) return null;
  return (
    <Text type="secondary" style={{ fontSize: 12 }}>
      当前班表共 {entries.length} 条记录；已发布条目使用班次快照，后续修改或停用班次模板不会改变历史时间。
    </Text>
  );
}
