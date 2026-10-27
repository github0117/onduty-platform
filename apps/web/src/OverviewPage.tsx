import {
  Alert,
  Button,
  Card,
  Col,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useQuery } from "@tanstack/react-query";

import {
  listCustomerConversations,
  listDigitalEmployees,
  listKnowledgeEvaluationCases,
  listKnowledgeSpaces,
  listMcpToolApprovals,
} from "./api";
import { getActiveBusinessUnitId } from "./auth";

const { Paragraph, Text, Title } = Typography;

type OverviewEntry = {
  path: string;
  label: string;
  description: string;
};

const sections: Array<{
  title: string;
  eyebrow: string;
  description: string;
  entries: OverviewEntry[];
}> = [
  {
    title: "业务场景",
    eyebrow: "AGENT DEMO",
    description: "从同一个员工池和入口验证跨岗位分派，再看电商与内部工单的复用。",
    entries: [
      {
        path: "/customer-service",
        label: "企业服务台主演示",
        description: "研发、HR、企业服务台员工按问题自动分派",
      },
      {
        path: "/customer-service/workbench",
        label: "人工工作台",
        description: "接管、审核建议、回复和交接",
      },
      {
        path: "/ecommerce",
        label: "电商运营复用",
        description: "商品、上架审核、视觉内容和发布异常",
      },
      {
        path: "/tickets",
        label: "内部工单 / HR",
        description: "服务请求、入职任务和外部同步",
      },
    ],
  },
  {
    title: "员工与路由",
    eyebrow: "WORKFORCE",
    description: "查看员工能力快照，再用固定问题验证入口分派是否可靠。",
    entries: [
      {
        path: "/employees/roster",
        label: "员工状态",
        description: "资源就绪度、配置版本和上岗状态",
      },
      {
        path: "/employees/routing",
        label: "业务入口与分派",
        description: "入口员工池、意图规则和兜底员工",
      },
      {
        path: "/employees/route-evaluation",
        label: "路由评测",
        description: "TUNING / HOLDOUT 准确率与失败分析",
      },
      {
        path: "/employees/drafts",
        label: "上岗审核",
        description: "评审、试用、发布和回滚",
      },
    ],
  },
  {
    title: "知识与评测",
    eyebrow: "KNOWLEDGE & RAG",
    description: "从空间和文档一路检查到检索、评测和修复闭环。",
    entries: [
      {
        path: "/knowledge/spaces",
        label: "知识空间",
        description: "按渠道、品类和业务归属组织资料",
      },
      {
        path: "/knowledge/documents",
        label: "知识文档",
        description: "版本、发布、归档和引用来源",
      },
      {
        path: "/knowledge/search",
        label: "检索调试",
        description: "检查命中文档、片段和分数",
      },
      {
        path: "/knowledge/evaluation",
        label: "质量评测",
        description: "召回、排序、拒答和修复回归",
      },
    ],
  },
  {
    title: "治理与审计",
    eyebrow: "GOVERNANCE",
    description: "把外部写操作、执行异常、模型成本和证据质量放在同一条审计链里。",
    entries: [
      {
        path: "/customer-service/approvals",
        label: "写操作审批",
        description: "独立审批人、版本校验和幂等执行",
      },
      {
        path: "/customer-service/incidents",
        label: "执行异常",
        description: "先对账再决定重试、补偿或关闭",
      },
      {
        path: "/models",
        label: "模型与连接",
        description: "模型用途、连接器和员工路由",
      },
      {
        path: "/operations",
        label: "运行与审计",
        description: "Trace、ToolCall、成本和同步告警",
      },
    ],
  },
];

function countLabel(
  query: { isError: boolean; isLoading: boolean },
  value: number | undefined,
): string {
  if (query.isError) return "-";
  if (query.isLoading) return "…";
  return String(value ?? "-");
}

export default function OverviewPage({
  onNavigate,
  onOpenGuide,
}: {
  onNavigate: (path: string) => void;
  onOpenGuide?: () => void;
}) {
  const employees = useQuery({
    queryKey: ["overview", "employees"],
    queryFn: listDigitalEmployees,
    retry: false,
  });
  const conversations = useQuery({
    queryKey: ["overview", "conversations"],
    queryFn: listCustomerConversations,
    retry: false,
  });
  const spaces = useQuery({
    queryKey: ["overview", "knowledge-spaces"],
    queryFn: listKnowledgeSpaces,
    retry: false,
  });
  const evaluationCases = useQuery({
    queryKey: ["overview", "evaluation-cases"],
    queryFn: listKnowledgeEvaluationCases,
    retry: false,
  });
  const approvals = useQuery({
    queryKey: ["overview", "pending-approvals"],
    queryFn: () => listMcpToolApprovals("PENDING"),
    retry: false,
  });

  const activeEmployees = employees.data?.filter(
    (employee) => employee.status === "ACTIVE",
  ).length;
  const activeSpaces = spaces.data?.filter(
    (space) => space.status === "ACTIVE" && space.domain !== "e2e",
  ).length;
  const enabledCases = evaluationCases.data?.filter(
    (item) => item.enabled,
  ).length;
  const errors = [
    employees,
    conversations,
    spaces,
    evaluationCases,
    approvals,
  ].filter((query) => query.isError);

  return (
    <Space direction="vertical" size="large" className="page-stack">
      <section className="overview-hero">
        <div className="overview-hero-copy">
          <Space size={8} wrap>
            <Tag color="gold">平台总览</Tag>
            <Tag color="cyan">{getActiveBusinessUnitId()} · 演示租户</Tag>
          </Space>
          <Title level={1}>
            先看平台全景，
            <br />
            再进入一条可核验的主链。
          </Title>
          <Paragraph>
            这里把业务场景、数字员工、知识评测和治理审计放在同一张地图上。
            第一眼看广度，点击任意入口查看真实数据；主演示仍然从企业服务台开始。
          </Paragraph>
          <Space wrap size="middle">
            <Button
              type="primary"
              size="large"
              onClick={() => onNavigate("/customer-service")}
            >
              进入 60 秒主演示
            </Button>
            <Button size="large" onClick={() => onNavigate("/employees/routing")}>
              查看员工如何分派
            </Button>
            {onOpenGuide && (
              <Button size="large" type="text" onClick={onOpenGuide}>
                打开 5 步技术演示
              </Button>
            )}
          </Space>
        </div>
        <div className="overview-hero-stats">
          <Card className="overview-stat-card" size="small">
            <Statistic
              title="已上岗员工"
              value={countLabel(employees, activeEmployees)}
              suffix="名"
            />
          </Card>
          <Card className="overview-stat-card" size="small">
            <Statistic
              title="当前会话"
              value={countLabel(conversations, conversations.data?.total)}
              suffix="个"
            />
          </Card>
          <Card className="overview-stat-card" size="small">
            <Statistic
              title="可用知识空间"
              value={countLabel(spaces, activeSpaces)}
              suffix="个"
            />
          </Card>
          <Card className="overview-stat-card" size="small">
            <Statistic
              title="启用评测案例"
              value={countLabel(evaluationCases, enabledCases)}
              suffix="条"
            />
          </Card>
          <Card className="overview-stat-card" size="small">
            <Statistic
              title="待审批写操作"
              value={countLabel(approvals, approvals.data?.total)}
              suffix="项"
            />
          </Card>
        </div>
      </section>

      {errors.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message="部分总览数据暂时不可用"
          description="数字以“-”显示，避免把权限失败或服务异常误读成真实的 0。请打开对应模块检查。"
        />
      )}

      <Row gutter={[16, 16]}>
        {sections.map((section) => (
          <Col xs={24} xl={12} key={section.title}>
            <Card className="overview-section-card">
              <div className="overview-section-heading">
                <div>
                  <Text className="overview-eyebrow">{section.eyebrow}</Text>
                  <Title level={3}>{section.title}</Title>
                  <Paragraph type="secondary">{section.description}</Paragraph>
                </div>
                <span className="overview-section-count">
                  {section.entries.length} 个入口
                </span>
              </div>
              <div className="overview-entry-list">
                {section.entries.map((entry) => (
                  <button
                    className="overview-entry"
                    key={entry.path}
                    type="button"
                    onClick={() => onNavigate(entry.path)}
                  >
                    <span>
                      <strong>{entry.label}</strong>
                      <small>{entry.description}</small>
                    </span>
                    <span aria-hidden="true" className="overview-entry-arrow">
                      →
                    </span>
                  </button>
                ))}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Card className="overview-note-card" size="small">
        <Space direction="vertical" size={6}>
          <Text strong>演示管理员说明</Text>
          <Text type="secondary">
            管理员身份保留全部菜单，便于第一眼看到平台内容；写操作仍按角色能力和后端权限执行。
            演示数据恢复只针对当前演示租户，并在后台运行。
          </Text>
        </Space>
      </Card>
    </Space>
  );
}
