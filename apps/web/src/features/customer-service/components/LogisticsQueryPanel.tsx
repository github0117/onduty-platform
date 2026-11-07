import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Space,
  Tag,
  Timeline,
  Typography,
} from "antd";

import type { useReplyMutations } from "../useReplyMutations";

const { Text } = Typography;

interface LogisticsQueryPanelProps {
  logisticsConfigured: boolean;
  logisticsOrderId: string;
  setLogisticsOrderId: (value: string) => void;
  trackingNumber: string;
  setTrackingNumber: (value: string) => void;
  carrierCode: string;
  setCarrierCode: (value: string) => void;
  logistics: ReturnType<typeof useReplyMutations>["logistics"];
}

export function LogisticsQueryPanel({
  logisticsConfigured,
  logisticsOrderId,
  setLogisticsOrderId,
  trackingNumber,
  setTrackingNumber,
  carrierCode,
  setCarrierCode,
  logistics,
}: LogisticsQueryPanelProps) {
  return (
    <Card size="small" title="物流查询" style={{ marginTop: 16 }}>
      <Space
        direction="vertical"
        size="middle"
        style={{ width: "100%" }}
      >
        <Alert
          type={logisticsConfigured ? "success" : "warning"}
          showIcon
          message={
            logisticsConfigured
              ? "已配置真实物流查询接口"
              : "物流查询接口尚未配置"
          }
          description={
            logisticsConfigured
              ? "查询结果来自企业订单或物流服务，不会由模型猜测。"
              : "请先取得订单号或运单号，并配置企业 OMS、WMS 或快递查询接口。系统当前不会生成虚假物流状态。"
          }
        />
        <Input
          value={logisticsOrderId}
          onChange={(event) => setLogisticsOrderId(event.target.value)}
          placeholder="订单号（可选，订单号和运单号至少填一个）"
          disabled={!logisticsConfigured}
        />
        <Input
          value={trackingNumber}
          onChange={(event) => setTrackingNumber(event.target.value)}
          placeholder="运单号，例如 SF1234567890"
          disabled={!logisticsConfigured}
        />
        <Input
          value={carrierCode}
          onChange={(event) => setCarrierCode(event.target.value)}
          placeholder="快递公司编码（可选），例如 SF、YTO、ZTO"
          disabled={!logisticsConfigured}
        />
        <Button
          loading={logistics.isPending}
          disabled={
            !logisticsConfigured ||
            (!logisticsOrderId.trim() && !trackingNumber.trim())
          }
          onClick={() => logistics.mutate()}
        >
          查询真实物流状态
        </Button>
        {logistics.data && (
          <Card size="small" title="最新物流状态">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="状态">
                <Tag color="blue">{logistics.data.status_label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="运单号">
                {logistics.data.tracking_number ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="快递公司">
                {logistics.data.carrier_code ?? "-"}
              </Descriptions.Item>
              <Descriptions.Item label="更新时间">
                {logistics.data.latest_event_at
                  ? new Date(
                      logistics.data.latest_event_at,
                    ).toLocaleString()
                  : "-"}
              </Descriptions.Item>
            </Descriptions>
            {logistics.data.events.length > 0 ? (
              <Timeline
                style={{ marginTop: 16 }}
                items={logistics.data.events.map((event) => ({
                  color: "blue",
                  children: (
                    <Space direction="vertical" size={0}>
                      <Text strong>{event.description}</Text>
                      <Text type="secondary">
                        {event.location ?? "位置未知"} ·{" "}
                        {event.occurred_at
                          ? new Date(event.occurred_at).toLocaleString()
                          : "时间未知"}
                      </Text>
                    </Space>
                  ),
                }))}
              />
            ) : (
              <Text type="secondary">物流服务暂未返回轨迹明细。</Text>
            )}
          </Card>
        )}
      </Space>
    </Card>
  );
}
