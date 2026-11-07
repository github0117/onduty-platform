import {
  Alert,
  Button,
  Card,
  Col,
  Row,
  Space,
  Steps,
  Tag,
  Typography,
} from "antd";
import type { RefObject } from "react";

import {
  type CustomerServiceSurfaceMode,
} from "../model";
import type { useTicketMutations } from "../useTicketMutations";

const { Text } = Typography;

const guidedScenarios = [
  {
    key: "presales",
    emoji: "🛍️",
    title: "商品咨询",
    description: "查看知识库回答与商品引用",
    subject: "保温杯材质和保温时长咨询",
    body: "你好，这款保温杯是什么材质，能保温多久？",
    tag: "低风险",
    color: "green",
  },
  {
    key: "logistics",
    emoji: "🚚",
    title: "物流查询",
    description: "体验实时 MCP 工具与工具审计",
    subject: "订单物流进度查询",
    body: "我的订单 DEMO-ORDER-1001 到哪了？请查询实时物流状态。",
    tag: "只读工具",
    color: "blue",
  },
  {
    key: "refund",
    emoji: "🛡️",
    title: "退款审批",
    description: "体验风险判断、写审批和人工接管",
    subject: "保温杯破损退款申请",
    body: "订单 DEMO-ORDER-2001 的保温杯破损，申请退款 59.9 元，请走人工审批。",
    tag: "高风险",
    color: "volcano",
  },
] as const;

export type GuidedScenario = (typeof guidedScenarios)[number];

interface GuideWalkthroughPanelProps {
  guidedStep: number;
  setViewMode: (value: CustomerServiceSurfaceMode) => void;
  assignment: ReturnType<typeof useTicketMutations>["assignment"];
  createTicket: ReturnType<typeof useTicketMutations>["createTicket"];
  ticketPanelRef: RefObject<HTMLDivElement | null>;
  runGuidedScenario: (scenario: GuidedScenario) => void;
}

export function GuideWalkthroughPanel({
  guidedStep,
  setViewMode,
  assignment,
  createTicket,
  ticketPanelRef,
  runGuidedScenario,
}: GuideWalkthroughPanelProps) {
  return (
    <Card
      className="section-card"
      title="第一次使用？按这 4 步完成一次测试"
      extra={
        <Button
          onClick={() => setViewMode("workspace")}
        >
          查看全部会话
        </Button>
      }
    >
      <Steps
        current={guidedStep}
        items={[
          {
            title: "发起测试问题",
            description: "任选下面一个场景",
          },
          {
            title: "自动分配",
            description: "系统按技能与负载派给你",
          },
          {
            title: "生成或修改回复",
            description: "确认后才会发送",
          },
          {
            title: "标记解决",
            description: "完成一次闭环",
          },
        ]}
      />
      <Alert
        style={{ marginTop: 20 }}
        type="info"
        showIcon
        message={
          guidedStep === 0
            ? "当前下一步：选一个场景，系统会自动创建测试会话"
            : guidedStep === 1
              ? "当前下一步：系统等待符合条件的在线坐席；若你是兜底人员，也可手动接管"
              : guidedStep === 2
                ? "系统已将会话分配给你，AI 草稿也已自动生成；确认内容后即可发送"
                : "当前会话已解决，可以从场景卡片重新开始"
        }
        description={
          <Space wrap>
            <Text>
              数字员工负责自动分析；你负责确认、改写和承担最终结果。
            </Text>
            {guidedStep === 1 && (
              <Button
                type="primary"
                loading={assignment.isPending}
                onClick={() => assignment.mutate("takeover")}
              >
                接管当前会话
              </Button>
            )}
            {guidedStep === 2 && (
              <Button
                onClick={() =>
                  ticketPanelRef.current?.scrollIntoView({
                    behavior: "smooth",
                    block: "start",
                  })
                }
              >
                进入当前处理区
              </Button>
            )}
          </Space>
        }
      />
      <Row gutter={[12, 12]} style={{ marginTop: 20 }}>
        {guidedScenarios.map((scenario) => (
          <Col xs={24} lg={8} key={scenario.key}>
            <Card
              hoverable
              size="small"
              onClick={() => runGuidedScenario(scenario)}
              style={{ height: "100%", cursor: "pointer" }}
            >
              <Space direction="vertical" size={8}>
                <Space>
                  <span style={{ fontSize: 24 }}>{scenario.emoji}</span>
                  <Text strong>{scenario.title}</Text>
                  <Tag color={scenario.color}>{scenario.tag}</Tag>
                </Space>
                <Text type="secondary">{scenario.description}</Text>
                <Text ellipsis style={{ maxWidth: 320 }}>
                  “{scenario.body}”
                </Text>
                <Button
                  type={scenario.key === "presales" ? "primary" : "default"}
                  loading={createTicket.isPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    runGuidedScenario(scenario);
                  }}
                >
                  用这个场景开始
                </Button>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
      <Alert
        style={{ marginTop: 16 }}
        type="success"
        showIcon
        message="看不懂这些词？"
        description="接管：锁定由你处理，避免多人抢同一会话。回复建议：只是草稿，不会自动发给用户。审批：退款、取消等写操作必须先由另一名主管或管理员确认。"
      />
    </Card>
  );
}
