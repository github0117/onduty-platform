import { Card, Col, Row, Tag, Typography } from "antd";

import type { TicketDetail } from "../../../types";
import { riskLevels, ticketOutcome } from "../model";

const { Paragraph, Text } = Typography;

interface TicketOutcomeCardProps {
  ticket: TicketDetail;
}

export function TicketOutcomeCard({ ticket }: TicketOutcomeCardProps) {
  const outcome = ticketOutcome(ticket);
  const riskDescription =
    riskLevels.find(
      (level) => level.code === ticket.risk?.level,
    )?.description ?? ticket.risk?.level;
  const completed = [
    "已识别买家问题和业务分类",
    ticket.risk?.level
      ? `已完成风险判断：${riskDescription}`
      : null,
    ticket.draft?.citations.length
      ? `已找到 ${ticket.draft.citations.length} 条企业知识依据`
      : null,
    ticket.draft
      ? "已生成可审核的回复草稿"
      : "尚未生成回复草稿",
  ].filter(Boolean);
  return (
    <Card
      size="small"
      title="为什么这样处理"
      extra={
        <Tag color={outcome.color}>{outcome.title}</Tag>
      }
      style={{ marginTop: 16 }}
    >
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Text strong>数字员工已完成</Text>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            {completed.join("；")}。
          </Paragraph>
        </Col>
        <Col xs={24} lg={8}>
          <Text strong>处理结论</Text>
          <Paragraph style={{ marginTop: 8 }}>
            {outcome.reason}
          </Paragraph>
        </Col>
        <Col xs={24} lg={8}>
          <Text strong>下一步</Text>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            {outcome.nextStep}
          </Paragraph>
        </Col>
      </Row>
    </Card>
  );
}
