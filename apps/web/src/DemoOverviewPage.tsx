import {
  Alert,
  Button,
  Card,
  Col,
  Modal,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getRagMetrics,
  getToolMetrics,
  listDigitalEmployees,
  listMcpConnectors,
  resetDemoData,
} from "./api";
import { getActiveTestIdentity } from "./auth";
import { message } from "./feedback";

const { Paragraph, Text, Title } = Typography;

const scenarioCards = [
  {
    path: "/customer-service?scenario=enterprise",
    title: "研发支持 Agent：查询真实 GitHub 仓库",
    label: "主演示 · 真实外部 MCP",
    color: "cyan",
    description:
      "提出一个公开仓库问题，观察系统如何路由到研发支持员工、检索授权知识、规划 DeepWiki MCP、执行只读工具并生成引用。",
    capabilities: ["Skill 路由", "RAG", "LangGraph", "MCP ToolCall", "Trace"],
    primary: true,
  },
  {
    path: "/customer-service?scenario=ecommerce",
    title: "电商客服复用案例",
    label: "复用案例 · 可选",
    color: "blue",
    description:
      "同一套员工、知识和工具能力用于商品咨询、物流查询、退款审批与人工接管。",
    capabilities: ["商品知识", "物流查询", "风险分级", "人工审批"],
    primary: false,
  },
  {
    path: "/ecommerce/products",
    title: "电商运营复用案例",
    label: "复用案例 · 可选",
    color: "geekblue",
    description:
      "展示商品资料、内容生成与人工审核如何复用相同的员工和资源模型。",
    capabilities: ["商品资料", "AI 主图", "上架生成", "内容审核"],
    primary: false,
  },
  {
    path: "/tickets",
    title: "内部工单与 HR 复用案例",
    label: "复用案例 · 可选",
    color: "purple",
    description:
      "演示内部服务请求和入职资料收集如何复用同一套工单、权限与审计能力。",
    capabilities: ["内部服务", "HR 入职", "人工复核", "工单同步"],
    primary: false,
  },
];

const capabilityLayers = [
  {
    index: "01",
    title: "应用与数据层",
    description: "FastAPI、SQLAlchemy、Alembic、PostgreSQL 和 React 构成应用底座。",
    path: "/models/integrations",
  },
  {
    index: "02",
    title: "Agent 编排层",
    description: "LangGraph 串联 Skill 路由、知识检索、MCP 工具规划和回复生成。",
    path: "/employees/skills",
  },
  {
    index: "03",
    title: "知识与工具层",
    description: "RAG 提供可追溯知识，MCP 连接真实外部只读或审批型工具。",
    path: "/employees/integrations",
  },
  {
    index: "04",
    title: "可靠性与治理",
    description: "RBAC、多租户、幂等、审批、对账、ToolCall、Trace 和成本全部留痕。",
    path: "/operations",
  },
];

const agentExecutionNodes = [
  ["1", "用户任务", "查询公开仓库", "trigger"],
  ["2", "员工路由", "研发支持员工", "ai"],
  ["3", "知识检索", "授权规范命中", "tool"],
  ["4", "工具规划", "DeepWiki MCP", "ai"],
  ["5", "工具执行", "只读文档查询", "tool"],
  ["6", "结果治理", "引用 + Trace", "end"],
] as const;

export default function DemoOverviewPage({
  onNavigate,
  onStartGuide,
}: {
  onNavigate: (path: string) => void;
  onStartGuide: () => void;
}) {
  const [resetOpen, setResetOpen] = useState(false);
  const queryClient = useQueryClient();
  const activeIdentity = getActiveTestIdentity();
  const canResetDemo = activeIdentity.id === "platform-admin";
  const ragMetrics = useQuery({
    queryKey: ["demo-overview-rag-metrics"],
    queryFn: getRagMetrics,
  });
  const employees = useQuery({
    queryKey: ["demo-overview-employees"],
    queryFn: listDigitalEmployees,
  });
  const toolMetrics = useQuery({
    queryKey: ["demo-overview-tool-metrics"],
    queryFn: getToolMetrics,
  });
  const mcpConnectors = useQuery({
    queryKey: ["demo-overview-mcp-connectors"],
    queryFn: listMcpConnectors,
  });
  const resetDemo = useMutation({
    mutationFn: resetDemoData,
    onSuccess: async (result) => {
      setResetOpen(false);
      message.success(result.message);
      await queryClient.invalidateQueries();
    },
    onError: (error: Error) => message.error(error.message),
  });
  const externalMcpToolCount =
    mcpConnectors.data
      ?.filter(
        (connector) =>
          connector.status === "ACTIVE" &&
          connector.code === "deepwiki-public",
      )
      .reduce((total, connector) => total + connector.tools.length, 0) ?? 0;

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <section className="demo-hero">
        <div className="demo-hero-copy">
          <Tag color="cyan">AI 应用开发 · 固定技术演示</Tag>
          <Title level={2}>
            研发支持 Agent：从 RAG 到真实 MCP 工具调用
          </Title>
          <Paragraph>
            按一条固定主线演示：数字员工上岗检查、授权知识检索、LangGraph
            Skill 路由、DeepWiki MCP 工具规划、ToolCall 执行和引用审计。
            电商、HR 和内容场景只作为同一底座上的复用案例。
          </Paragraph>
          <Space wrap>
            <Button
              type="primary"
              size="large"
              onClick={onStartGuide}
            >
              开始 5 步技术演示
            </Button>
            <Button
              size="large"
              onClick={() =>
                onNavigate("/customer-service?scenario=enterprise")
              }
            >
              直接进入主演示
            </Button>
            {canResetDemo && (
              <Button
                size="large"
                loading={resetDemo.isPending}
                onClick={() => setResetOpen(true)}
              >
                检查并恢复演示数据
              </Button>
            )}
          </Space>
        </div>
        <div className="demo-flow">
          {[
            ["用户任务", "查询公开 GitHub 仓库"],
            ["员工路由", "研发支持数字员工"],
            ["Agent 执行", "Skill + RAG + DeepWiki MCP"],
            ["工程证据", "引用 + ToolCall + Trace"],
          ].map(([title, description], index) => (
            <div className="demo-flow-step" key={title}>
              <span>{index + 1}</span>
              <div>
                <Text strong>{title}</Text>
                <Text type="secondary">{description}</Text>
              </div>
            </div>
          ))}
        </div>
      </section>

      <Alert
        type="info"
        showIcon
        message="只看这一条主线就够"
        description="推荐顺序：技术总览 → 员工与 Skill/MCP → 研发支持对话 → ToolCall 与 Trace。电商、HR 和内容生产是复用案例，演示时不需要逐个演示。"
      />

      <Card
        className="section-card"
        title="技术验收证据"
        extra={<Tag color="blue">当前运行数据</Tag>}
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} xl={6}>
            <Card size="small">
              <Statistic
                title="已上岗员工"
                value={
                  employees.data?.filter(
                    (employee) => employee.status === "ACTIVE",
                  ).length ?? 0
                }
                suffix="名"
              />
              <Text type="secondary">
                包含研发支持、客服、运营和 HR 岗位
              </Text>
            </Card>
          </Col>
          <Col xs={12} xl={6}>
            <Card size="small">
              <Statistic
                title="知识有依据率"
                value={Math.round(
                  (ragMetrics.data?.grounding_rate ?? 0) * 100,
                )}
                suffix="%"
              />
              <Text type="secondary">
                草稿 {ragMetrics.data?.draft_count ?? 0} 份 · 引用{" "}
                {ragMetrics.data?.citation_total ?? 0} 条
              </Text>
            </Card>
          </Col>
          <Col xs={12} xl={6}>
            <Card size="small">
              <Statistic
                title="DeepWiki 只读工具"
                value={externalMcpToolCount}
                suffix="个"
              />
              <Text type="secondary">
                真实外部 Streamable HTTP MCP
              </Text>
            </Card>
          </Col>
          <Col xs={12} xl={6}>
            <Card size="small">
              <Statistic
                title="ToolCall 成功率"
                value={Math.round(
                  (toolMetrics.data?.success_rate ?? 0) * 100,
                )}
                suffix="%"
              />
              <Text type="secondary">
                共调用 {toolMetrics.data?.calls ?? 0} 次 · 失败{" "}
                {toolMetrics.data?.failed ?? 0} 次
              </Text>
            </Card>
          </Col>
        </Row>
      </Card>

      <div>
        <div className="section-heading">
          <div>
            <Title level={3}>一条主演示 + 三个复用案例</Title>
            <Paragraph type="secondary">
              先把研发支持主链讲透，再说明同一底座可以复用到其他业务。
            </Paragraph>
          </div>
          <Tag color="gold">先主链，后复用</Tag>
        </div>
        <Row gutter={[16, 16]}>
          {scenarioCards.map((scenario) => (
            <Col
              xs={24}
              md={scenario.primary ? 24 : 12}
              xl={scenario.primary ? 24 : 8}
              key={scenario.path}
            >
              <Card
                className={`scenario-card${
                  scenario.primary ? " scenario-card-primary" : ""
                }`}
                size="small"
              >
                <Space
                  direction="vertical"
                  size="middle"
                  style={{ width: "100%" }}
                >
                  <Space wrap>
                    <Tag color={scenario.color}>{scenario.label}</Tag>
                    <Text type="secondary">DEMO</Text>
                  </Space>
                  <Title level={4}>{scenario.title}</Title>
                  <Paragraph type="secondary">
                    {scenario.description}
                  </Paragraph>
                  <Space wrap size={[4, 4]}>
                    {scenario.capabilities.map((capability) => (
                      <Tag key={capability}>{capability}</Tag>
                    ))}
                  </Space>
                  <Button
                    type="link"
                    className="scenario-link"
                    onClick={() => onNavigate(scenario.path)}
                  >
                    {scenario.primary
                      ? "开始研发支持主演示 →"
                      : "查看复用案例 →"}
                  </Button>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      </div>

      <div>
        <div className="section-heading">
          <div>
            <Title level={3}>技术实现主线</Title>
            <Paragraph type="secondary">
              演示时按以下四层解释实现，不需要逐个业务页面介绍。
            </Paragraph>
          </div>
        </div>
        <Row gutter={[16, 16]}>
          {capabilityLayers.map((layer) => (
            <Col xs={24} md={12} xl={6} key={layer.index}>
              <Card
                className="capability-card"
                hoverable
                onClick={() => onNavigate(layer.path)}
              >
                <span className="capability-index">{layer.index}</span>
                <Title level={4}>{layer.title}</Title>
                <Paragraph type="secondary">
                  {layer.description}
                </Paragraph>
                <Text className="capability-link">查看能力配置 →</Text>
              </Card>
            </Col>
          ))}
        </Row>
      </div>

      <Card
        className="section-card"
        title="研发支持 Agent 的实际执行链"
        extra={<Tag color="green">已跑通真实 MCP</Tag>}
      >
        <Paragraph type="secondary">
          用户提出公开仓库问题后，系统沿以下链路完成处理，并将每一步写入 Trace。
        </Paragraph>
        <div className="workflow-blueprint">
          {agentExecutionNodes.map(([group, title, type], index) => (
            <div className="workflow-node-wrap" key={`${group}-${title}`}>
              <div className={`workflow-node workflow-node-${type}`}>
                <Text type="secondary">{group}</Text>
                <Text strong>{title}</Text>
              </div>
              {index < agentExecutionNodes.length - 1 && (
                <span className="workflow-arrow">→</span>
              )}
            </div>
          ))}
        </div>
        <Alert
          type="info"
          showIcon
          message="对应 Trace"
          description="route_skill → retrieve_knowledge → plan_mcp_tools → execute_mcp_tool → generate_reply。真实 ToolCall 结果为 SUCCEEDED，并生成 source_type=mcp 引用。"
          style={{ marginTop: 16 }}
        />
      </Card>

      <Card className="section-card" title="当前演示的真实程度">
        <Row gutter={[20, 20]}>
          <Col xs={24} md={8}>
            <Space direction="vertical" size="small">
              <Tag color="green">已运行</Tag>
              <Text strong>真实外部 MCP 与 Agent 工具链</Text>
              <Text type="secondary">
                DeepWiki Streamable HTTP 连接、3 个只读工具发现、LangGraph 工具规划、
                ToolCall 成功和实时引用均已实际验证。
              </Text>
            </Space>
          </Col>
          <Col xs={24} md={8}>
            <Space direction="vertical" size="small">
              <Tag color="gold">沙盒或演示</Tag>
              <Text strong>企业业务数据</Text>
              <Text type="secondary">
                订单、物流、工单和企业消息仍使用可重复沙盒数据，用于展示同一套
                员工、审批和审计机制。
              </Text>
            </Space>
          </Col>
          <Col xs={24} md={8}>
            <Space direction="vertical" size="small">
              <Tag color="red">未接入生产</Tag>
              <Text strong>生产系统与真实业务收益</Text>
              <Text type="secondary">
                尚未完成企业 OIDC、生产消息渠道、真实订单物流、并发压测和真实用户试点，
                不宣称已经产生降本增效结果。
              </Text>
            </Space>
          </Col>
        </Row>
      </Card>

      <Modal
        title="检查并恢复演示数据？"
        open={resetOpen}
        onCancel={() => {
          if (!resetDemo.isPending) setResetOpen(false);
        }}
        onOk={() => resetDemo.mutate()}
        okText="开始恢复"
        cancelText="取消"
        confirmLoading={resetDemo.isPending}
        okButtonProps={{ disabled: resetDemo.isPending }}
        cancelButtonProps={{ disabled: resetDemo.isPending }}
      >
        <Space direction="vertical" size="middle">
          <Text>
            系统会检查并补齐固定演示所需的员工、知识、工单、商品和内容任务。
          </Text>
          <Alert
            type="info"
            showIcon
            message="这是幂等恢复，不会删除你手工创建的数据"
            description="固定演示数据已存在时会更新或复用；执行过程可能需要几十秒。仅演示或开发环境可执行。"
          />
        </Space>
      </Modal>
    </Space>
  );
}
