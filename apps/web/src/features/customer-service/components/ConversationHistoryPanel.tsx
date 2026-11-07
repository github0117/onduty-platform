import { Button, Card, Segmented, Space, Tag, Typography } from "antd";
import type { RefObject } from "react";

import type { CustomerMessage } from "../../../types";
import type { ConversationTurn, HistoryScope } from "../model";

const { Text } = Typography;

export interface HistoryEntry {
  id: string;
  role: "BUYER" | "ASSISTANT";
  text: string;
  createdAt: string | null;
  ticketId: string | null;
  createdBy: string | null;
  senderLabel: string;
  human: boolean;
}

interface ConversationHistoryPanelProps {
  followLatest: boolean;
  setFollowLatest: (value: boolean) => void;
  historyScope: HistoryScope;
  setHistoryScope: (value: HistoryScope) => void;
  historyContainerRef: RefObject<HTMLDivElement | null>;
  currentTicketMessageCount: number;
  conversationMessages: CustomerMessage[];
  history: ConversationTurn[];
  historyEntries: HistoryEntry[];
  currentTicketId: string | null | undefined;
}

export function ConversationHistoryPanel({
  followLatest,
  setFollowLatest,
  historyScope,
  setHistoryScope,
  historyContainerRef,
  currentTicketMessageCount,
  conversationMessages,
  history,
  historyEntries,
  currentTicketId,
}: ConversationHistoryPanelProps) {
  return (
    <Card
      title="会话历史"
      extra={
        <Space>
          {!followLatest && (
            <Button
              size="small"
              onClick={() => setFollowLatest(true)}
            >
              回到最新
            </Button>
          )}
          <Segmented
            size="small"
            value={historyScope}
            onChange={(value) => {
              setHistoryScope(value as HistoryScope);
              setFollowLatest(true);
            }}
            options={[
              {
                label: `当前工单 ${currentTicketMessageCount}`,
                value: "current",
              },
              {
                label: `全部历史 ${conversationMessages.length || history.length}`,
                value: "all",
              },
            ]}
          />
        </Space>
      }
    >
      <div
        ref={historyContainerRef}
        onScroll={(event) => {
          const container = event.currentTarget;
          const distanceToBottom =
            container.scrollHeight -
            container.scrollTop -
            container.clientHeight;
          setFollowLatest(distanceToBottom < 64);
        }}
        style={{
          maxHeight: "min(60vh, 620px)",
          overflowY: "auto",
          paddingRight: 8,
        }}
      >
        <Space
          direction="vertical"
          size="small"
          style={{ width: "100%" }}
        >
          {historyEntries.map((message, index) => {
            const showTicket =
              Boolean(message.ticketId) &&
              message.ticketId !== historyEntries[index - 1]?.ticketId;
            return (
              <div key={message.id}>
                {showTicket && (
                  <div style={{ textAlign: "center", margin: "8px 0" }}>
                    <Tag color={message.ticketId === currentTicketId ? "blue" : "default"}>
                      工单 {message.ticketId?.slice(0, 8)}
                      {message.ticketId === currentTicketId
                        ? " · 当前"
                        : ""}
                    </Tag>
                  </div>
                )}
                <div
                  style={{
                    display: "flex",
                    justifyContent:
                      message.role === "BUYER" ? "flex-start" : "flex-end",
                  }}
                >
                  <Card
                    size="small"
                    style={{
                      maxWidth: "82%",
                      background:
                        message.role === "BUYER"
                          ? "#f5f5f5"
                          : message.human
                            ? "#f6ffed"
                            : "#e6f4ff",
                    }}
                  >
                    <Space
                      direction="vertical"
                      size={4}
                      style={{ width: "100%" }}
                    >
                      <Space size={6}>
                        <Text strong>{message.senderLabel}</Text>
                        {message.createdAt && (
                          <Text type="secondary">
                            {new Date(message.createdAt).toLocaleString()}
                          </Text>
                        )}
                      </Space>
                      <Text style={{ whiteSpace: "pre-wrap" }}>
                        {message.text}
                      </Text>
                    </Space>
                  </Card>
                </div>
              </div>
            );
          })}
          {historyEntries.length === 0 && (
            <Text type="secondary">当前工单暂无消息</Text>
          )}
        </Space>
      </div>
    </Card>
  );
}
