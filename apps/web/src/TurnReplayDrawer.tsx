import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Table,
  Tag,
  Timeline,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  getCustomerConversationTurn,
  listCustomerConversationHandoffs,
  listCustomerConversationTurnEvents,
  listCustomerConversationTurns,
} from "./api";
import {
  gateDecisionLabels,
  gateReasonLabel,
  groundingStatusLabels,
  handoffKindLabels,
  handoffReasonLabels,
  localizedLabel,
  turnEventTypeLabels,
  turnStatusLabels,
} from "./statusLabels";
import type {
  ConversationHandoff,
  ConversationTurn,
  ConversationTurnEvent,
  ConversationTurnEventList,
} from "./types";

const { Text } = Typography;

const EVENT_PAGE_SIZE = 100;

function handoffEndpoints(handoff: ConversationHandoff): string {
  if (handoff.kind === "HUMAN_TAKEOVER") {
    return `${handoff.from_employee_name ?? "数字员工"} → 人工`;
  }
  if (handoff.kind === "HUMAN_RETURN") {
    return `人工 → ${handoff.to_employee_name ?? "数字员工"}`;
  }
  return `${handoff.from_employee_name ?? "数字员工"} → ${
    handoff.to_employee_name ?? "接手员工"
  }`;
}

function statusColor(status: string): string {
  if (status === "COMPLETED") return "green";
  if (status === "RUNNING") return "blue";
  if (status === "PENDING") return "gold";
  if (status === "NEEDS_HUMAN") return "orange";
  if (status === "CANCELLED") return "default";
  return "red";
}

function eventColor(eventType: string): string {
  if (eventType === "TURN_FAILED" || eventType === "TURN_FAILED_TERMINAL") {
    return "red";
  }
  if (eventType === "TURN_CANCELLED") return "gray";
  if (eventType === "GATE_EVALUATED" || eventType === "COMPLETION_EVALUATED") {
    return "blue";
  }
  if (eventType === "CONTEXT_ASSEMBLED" || eventType === "SKILL_SELECTED") {
    return "cyan";
  }
  return "green";
}

function time(value: string): string {
  return new Date(value).toLocaleString();
}

function JsonBlock({
  title,
  value,
}: {
  title: string;
  value: Record<string, unknown> | null;
}) {
  if (!value) return null;
  return (
    <div>
      <Text strong>{title}</Text>
      <pre className="trace-detail">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

export default function TurnReplayDrawer({
  conversationId,
  focusTurnId,
  open,
  onClose,
}: {
  conversationId: string;
  focusTurnId?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const [selectedTurnId, setSelectedTurnId] = useState("");
  const [extraEvents, setExtraEvents] = useState<ConversationTurnEvent[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState("");

  const turns = useQuery({
    queryKey: ["conversation-turns", conversationId],
    queryFn: () => listCustomerConversationTurns(conversationId, 50),
    enabled: open && Boolean(conversationId),
  });
  const detail = useQuery({
    queryKey: ["conversation-turn", conversationId, selectedTurnId],
    queryFn: () => getCustomerConversationTurn(conversationId, selectedTurnId),
    enabled: open && Boolean(conversationId) && Boolean(selectedTurnId),
  });
  const events = useQuery({
    queryKey: ["conversation-turn-events", conversationId, selectedTurnId],
    queryFn: () =>
      listCustomerConversationTurnEvents(conversationId, selectedTurnId, {
        limit: EVENT_PAGE_SIZE,
      }),
    enabled: open && Boolean(conversationId) && Boolean(selectedTurnId),
  });
  const handoffs = useQuery({
    queryKey: ["conversation-handoffs", conversationId],
    queryFn: () => listCustomerConversationHandoffs(conversationId),
    enabled: open && Boolean(conversationId),
  });

  useEffect(() => {
    setExtraEvents([]);
    setLoadMoreError("");
  }, [conversationId, selectedTurnId]);

  useEffect(() => {
    if (events.data) setHasMore(events.data.has_more);
  }, [events.data]);

  useEffect(() => {
    if (!open) return;
    const items = turns.data?.items ?? [];
    if (items.length === 0) {
      if (selectedTurnId) setSelectedTurnId("");
      return;
    }
    if (items.some((item) => item.id === selectedTurnId)) return;
    const preferred = items.find((item) => item.id === focusTurnId);
    setSelectedTurnId(preferred?.id ?? items[0].id);
  }, [focusTurnId, open, selectedTurnId, turns.data]);

  const pageEvents: ConversationTurnEvent[] = events.data?.events ?? [];
  const allEvents = [...pageEvents, ...extraEvents];
  const eventTotal = events.data?.total ?? allEvents.length;

  const loadMore = async () => {
    const last = allEvents[allEvents.length - 1];
    if (!last) return;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page: ConversationTurnEventList =
        await listCustomerConversationTurnEvents(
          conversationId,
          selectedTurnId,
          {
            afterSequence: last.sequence,
            limit: EVENT_PAGE_SIZE,
          },
        );
      setExtraEvents((current) => [...current, ...page.events]);
      setHasMore(page.has_more);
    } catch (error) {
      setLoadMoreError(
        error instanceof Error ? error.message : "事件加载失败",
      );
    } finally {
      setLoadingMore(false);
    }
  };

  const turnColumns: ColumnsType<ConversationTurn> = [
    {
      title: "轮次",
      dataIndex: "sequence",
      width: 64,
      render: (value: number) => `#${value}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: string) => (
        <Tag color={statusColor(value)}>
          {localizedLabel(turnStatusLabels, value, value)}
        </Tag>
      ),
    },
    { title: "阶段", dataIndex: "stage_label" },
    {
      title: "门禁",
      dataIndex: "gate",
      width: 100,
      render: (gate: ConversationTurn["gate"]) =>
        gate ? (
          <Tag color={gate.decision === "AUTO_SEND" ? "green" : "gold"}>
            {localizedLabel(gateDecisionLabels, gate.decision, gate.decision)}
          </Tag>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 170,
      render: time,
    },
  ];

  const replay = detail.data;

  return (
    <Drawer
      width={860}
      open={open}
      onClose={onClose}
      title={`运行回放 · 会话 ${conversationId.slice(0, 8)}`}
      destroyOnClose
    >
      <Space direction="vertical" size="large" style={{ width: "100%" }}>
        {turns.isError && (
          <Alert
            type="error"
            showIcon
            message="轮次列表加载失败"
            description={(turns.error as Error).message}
          />
        )}
        <Table
          rowKey="id"
          size="small"
          columns={turnColumns}
          dataSource={turns.data?.items}
          loading={turns.isLoading}
          pagination={false}
          scroll={{ y: 220 }}
          locale={{ emptyText: <Empty description="暂无运行轮次" /> }}
          rowClassName={(record) =>
            record.id === selectedTurnId ? "turn-row-active" : ""
          }
          onRow={(record) => ({
            onClick: () => setSelectedTurnId(record.id),
            style: { cursor: "pointer" },
          })}
        />

        {selectedTurnId && (
          <>
            {detail.isError && (
              <Alert
                type="error"
                showIcon
                message="轮次详情加载失败"
                description={(detail.error as Error).message}
              />
            )}
            {replay && (
              <Descriptions column={2} size="small" bordered>
                <Descriptions.Item label="状态">
                  <Tag color={statusColor(replay.status)}>
                    {localizedLabel(
                      turnStatusLabels,
                      replay.status,
                      replay.status,
                    )}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="阶段">
                  {replay.stage_label}
                </Descriptions.Item>
                <Descriptions.Item label="尝试次数">
                  {replay.attempt_count}
                </Descriptions.Item>
                <Descriptions.Item label="证据状态">
                  {localizedLabel(
                    groundingStatusLabels,
                    replay.grounding_status,
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="员工配置版本">
                  {replay.employee_config_revision ?? "-"}
                </Descriptions.Item>
                <Descriptions.Item label="响应模型">
                  {replay.response_provider
                    ? `${replay.response_provider} · ${replay.response_model ?? "-"}`
                    : "-"}
                </Descriptions.Item>
                <Descriptions.Item label="Skill" span={2}>
                  {replay.skill_code
                    ? `${replay.skill_code} · v${replay.skill_version ?? "-"}`
                    : "-"}
                </Descriptions.Item>
                <Descriptions.Item label="关联 ID" span={2}>
                  <Text code>{replay.correlation_id ?? "-"}</Text>
                </Descriptions.Item>
                {replay.gate && (
                  <Descriptions.Item label="发送门禁" span={2}>
                    <Space wrap>
                      <Tag
                        color={
                          replay.gate.decision === "AUTO_SEND"
                            ? "green"
                            : "gold"
                        }
                      >
                        {localizedLabel(
                          gateDecisionLabels,
                          replay.gate.decision,
                          replay.gate.decision,
                        )}
                      </Tag>
                      {replay.gate.reasons.length > 0 ? (
                        <Text type="secondary">
                          {replay.gate.reasons.map(gateReasonLabel).join("；")}
                        </Text>
                      ) : (
                        <Text type="secondary">证据与 Skill 校验均通过</Text>
                      )}
                    </Space>
                  </Descriptions.Item>
                )}
                {(replay.error_code || replay.error_message) && (
                  <Descriptions.Item label="失败原因" span={2}>
                    <Text type="danger">
                      {replay.error_code} · {replay.error_message ?? "-"}
                    </Text>
                  </Descriptions.Item>
                )}
              </Descriptions>
            )}

            {events.isError && (
              <Alert
                type="error"
                showIcon
                message="事件加载失败"
                description={(events.error as Error).message}
              />
            )}
            {events.isLoading ? (
              <Text type="secondary">正在加载事件…</Text>
            ) : allEvents.length === 0 ? (
              <Empty description="本轮暂无事件" />
            ) : (
              <>
                <Text type="secondary">
                  共 {eventTotal} 个事件，已加载 {allEvents.length} 个
                </Text>
                <Timeline
                  items={allEvents.map((event) => ({
                    color: eventColor(event.event_type),
                    children: (
                      <div className="trace-event">
                        <Space wrap>
                          <Text strong>
                            {localizedLabel(
                              turnEventTypeLabels,
                              event.event_type,
                              event.event_type,
                            )}
                          </Text>
                          <Tag>
                            {localizedLabel(
                              turnStatusLabels,
                              event.status,
                              event.status,
                            )}
                          </Tag>
                          <Text type="secondary">
                            {event.actor_type} · {event.actor_id}
                          </Text>
                        </Space>
                        <Text type="secondary" className="trace-time">
                          {time(event.created_at)}
                        </Text>
                        {Object.keys(event.payload).length > 0 && (
                          <pre className="trace-detail">
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        )}
                      </div>
                    ),
                  }))}
                />
                {hasMore && (
                  <Button loading={loadingMore} onClick={loadMore}>
                    加载更多事件
                  </Button>
                )}
                {loadMoreError && (
                  <Alert
                    type="error"
                    showIcon
                    message="更多事件加载失败"
                    description={loadMoreError}
                  />
                )}
              </>
            )}

            {replay && (
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <JsonBlock title="本轮上下文快照" value={replay.context} />
                <JsonBlock title="Skill 契约快照" value={replay.skill_snapshot} />
                <JsonBlock title="完成度校验" value={replay.completion} />
              </Space>
            )}
          </>
        )}

        <div>
          <Text strong>交接记录</Text>
          {handoffs.isError ? (
            <Text type="secondary"> 暂无权限查看交接记录</Text>
          ) : (handoffs.data?.items.length ?? 0) === 0 ? (
            <Text type="secondary"> 暂无交接</Text>
          ) : (
            <Timeline
              style={{ marginTop: 12 }}
              items={(handoffs.data?.items ?? []).map((handoff) => ({
                color: "purple",
                children: (
                  <div className="trace-event">
                    <Space wrap>
                      <Tag>{localizedLabel(handoffKindLabels, handoff.kind)}</Tag>
                      <Tag>
                        {localizedLabel(
                          handoffReasonLabels,
                          handoff.reason_code,
                        )}
                      </Tag>
                      <Text>{handoffEndpoints(handoff)}</Text>
                    </Space>
                    <Text type="secondary" className="trace-time">
                      {time(handoff.created_at)} · {handoff.created_by}
                    </Text>
                    {handoff.summary.operator_reason && (
                      <Text type="secondary">
                        {handoff.summary.operator_reason}
                      </Text>
                    )}
                    {handoff.summary.last_answer?.by === "human" && (
                      <Text type="secondary">
                        人工最后回复：{handoff.summary.last_answer.text}
                      </Text>
                    )}
                  </div>
                ),
              }))}
            />
          )}
        </div>
      </Space>
    </Drawer>
  );
}
