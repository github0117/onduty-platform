import { Alert, Card, Table, Typography } from "antd";

import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";

const { Text } = Typography;

interface ServiceTrendPanelProps {
  historyMetrics: ReturnType<
    typeof useCustomerServiceQueries
  >["historyMetrics"];
}

export function ServiceTrendPanel({ historyMetrics }: ServiceTrendPanelProps) {
  return (
    <Card
      size="small"
      title="近 7 天客服趋势"
      extra={
        <Text type="secondary">
          平均首响{" "}
          {historyMetrics.data?.average_first_response_seconds == null
            ? "-"
            : `${historyMetrics.data.average_first_response_seconds} 秒`}
        </Text>
      }
    >
      {historyMetrics.isError && (
        <Alert
          type="error"
          showIcon
          message="近 7 天趋势加载失败"
          description="趋势数据不可用，不代表新增会话或首响时间为 0。"
          style={{ marginBottom: 12 }}
        />
      )}
      <Table
        rowKey="date"
        size="small"
        loading={historyMetrics.isLoading}
        dataSource={historyMetrics.data?.daily}
        pagination={{ pageSize: 10, showSizeChanger: true }}
        columns={[
          { title: "日期", dataIndex: "date" },
          { title: "新增会话", dataIndex: "conversations_created" },
          { title: "消息", dataIndex: "messages" },
          { title: "买家消息", dataIndex: "buyer_messages" },
          { title: "员工消息", dataIndex: "assistant_messages" },
          {
            title: "平均首响",
            dataIndex: "average_first_response_seconds",
            render: (value: number | null) =>
              value == null ? "-" : `${value} 秒`,
          },
        ]}
      />
    </Card>
  );
}
