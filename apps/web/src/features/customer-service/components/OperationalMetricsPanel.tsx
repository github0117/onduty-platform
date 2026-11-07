import { Alert, Card, Col, Row, Space, Statistic, Tag, Typography } from "antd";

import { riskLevels } from "../model";
import type { useCustomerServiceQueries } from "../useCustomerServiceQueries";

const { Text, Title } = Typography;

interface OperationalMetricsPanelProps {
  metrics: ReturnType<typeof useCustomerServiceQueries>["metrics"];
}

export function OperationalMetricsPanel({
  metrics,
}: OperationalMetricsPanelProps) {
  return (
    <>
      {metrics.isError && (
        <Alert
          type="error"
          showIcon
          message="运营指标加载失败"
          description="当前无法确认会话负载和 SLA 状态，指标不会以 0 代替。请检查权限或后端服务。"
        />
      )}
      <Row gutter={[12, 12]}>
        {[
          ["活动会话", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.active_conversations ?? 0],
          ["待接管", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.unassigned_conversations ?? 0],
          ["在线客服", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.online_agents ?? 0],
          ["SLA 超时", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.sla_overdue ?? 0],
          ["主管告警", metrics.isError ? "-" : metrics.isLoading ? "…" : metrics.data?.open_supervisor_notifications ?? 0],
          [
            "平均等待",
            metrics.isError
              ? "-"
              : metrics.isLoading
                ? "…"
                : `${Math.floor((metrics.data?.average_waiting_seconds ?? 0) / 60)} 分钟`,
          ],
        ].map(([label, value]) => (
          <Col xs={12} md={8} xl={4} key={String(label)}>
            <Card size="small">
              <Statistic title={label} value={value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        size="small"
        title="活动会话风险分布"
        extra={
          <Text type="secondary">
            待评估{" "}
            {metrics.isError
              ? "-"
              : metrics.isLoading
                ? "…"
                : metrics.data?.risk_counts?.UNKNOWN ?? 0}{" "}
            · 风险决定授权边界，优先级决定处理时效
          </Text>
        }
      >
        <Row gutter={[12, 12]}>
          {riskLevels.map((level) => (
            <Col xs={12} xl={6} key={level.code}>
              <Card size="small" className="metric-card">
                <Space direction="vertical" size={4}>
                  <Space>
                    <Tag color={level.color}>{level.code}</Tag>
                    <Text strong>{level.label}</Text>
                  </Space>
                  <Title level={3} style={{ margin: 0 }}>
                    {metrics.isError
                      ? "-"
                      : metrics.isLoading
                        ? "…"
                        : metrics.data?.risk_counts?.[level.code] ?? 0}
                  </Title>
                  <Text type="secondary">{level.description}</Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
    </>
  );
}
