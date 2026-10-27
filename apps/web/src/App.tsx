import { Button, Dropdown, Layout, Menu, Space, Spin, Tag, Typography } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState } from "react";

import type { EmployeeSection } from "./EmployeesPage";
import type { EcommerceSection } from "./EcommercePage";
import type { ModelsSection } from "./ModelsPage";
import type { CustomerServiceSection } from "./CustomerServicePage";
import type { KnowledgeSection } from "./KnowledgePage";
import { message } from "./feedback";
import {
  consumeIdentitySwitchNotice,
  isTestIdentityMode,
  switchTestIdentity,
  testIdentityProfiles,
  useAuth,
} from "./auth";
import AccessDenied from "./AccessDenied";
import type { Capability } from "./capabilities";
import { demoPerspectiveLabels } from "./demoPerspectives";

const OverviewPage = lazy(() => import("./OverviewPage"));
const DemoGuideDrawer = lazy(() => import("./DemoGuideDrawer"));
const TicketsPage = lazy(() => import("./TicketsPage"));
const EcommercePage = lazy(() => import("./EcommercePage"));
const CustomerServicePage = lazy(() => import("./CustomerServicePage"));
const EmployeesPage = lazy(() => import("./EmployeesPage"));
const ModelsPage = lazy(() => import("./ModelsPage"));
const KnowledgePage = lazy(() => import("./KnowledgePage"));
const OperationsPage = lazy(() => import("./OperationsPage"));

const { Header, Content, Sider } = Layout;
const { Title, Text } = Typography;

type RouteMeta = {
  title: string;
  description: string;
  category: "Agent 演示" | "平台管理";
};

const routeMeta: Record<string, RouteMeta> = {
  "/overview": {
    title: "平台总览 · 从场景到治理",
    description: "先看平台全景，再进入企业服务台主演示或具体配置",
    category: "平台管理",
  },
  "/tickets": {
    title: "应用场景 · 内部工单与 HR 演示",
    description: "演示内部服务请求、HR 入职任务、人工审核和外部同步",
    category: "Agent 演示",
  },
  "/customer-service": {
    title: "Agent 对话 · 企业服务台多员工分派",
    description: "一个入口绑定研发支持、HR 和企业服务台员工，按问题自动分派",
    category: "Agent 演示",
  },
  "/customer-service/workbench": {
    title: "人工客服 · 会话工作台",
    description: "人工接管当前会话、发送回复和审核建议",
    category: "Agent 演示",
  },
  "/customer-service/admin": {
    title: "客服主管 · 运营看板",
    description: "查看团队指标、趋势、排班和待接管队列",
    category: "Agent 演示",
  },
  "/customer-service/approvals": {
    title: "客服运营 · 待审批操作",
    description: "确认外部业务写操作并生成审计记录",
    category: "Agent 演示",
  },
  "/customer-service/incidents": {
    title: "客服运营 · 执行异常",
    description: "核对失败或结果不确定的外部操作",
    category: "Agent 演示",
  },
  "/ecommerce": {
    title: "电商运营 · 数字员工工作区",
    description: "商品上架、视觉内容和运营主管数字员工协作",
    category: "Agent 演示",
  },
  "/ecommerce/products": {
    title: "商品与素材 · 数字员工工作区",
    description: "维护商品资料，并查看素材由哪位数字员工负责",
    category: "Agent 演示",
  },
  "/ecommerce/listings": {
    title: "上架审核 · 人工与数字员工协作",
    description: "数字员工生成上架内容，人工完成审核和发布",
    category: "Agent 演示",
  },
  "/ecommerce/insights": {
    title: "电商运营 · 主管数字员工看板",
    description: "查看发布、返工、人工介入和视频渲染质量",
    category: "Agent 演示",
  },
  "/employees/roster": {
    title: "平台能力 · 数字员工管理",
    description: "管理岗位身份、资源状态和配置版本",
    category: "平台管理",
  },
  "/employees/templates": {
    title: "平台能力 · 岗位模板",
    description: "从模板创建、验证和复制数字员工岗位",
    category: "平台管理",
  },
  "/employees/skills": {
    title: "平台能力 · Skill 与 SOP",
    description: "配置岗位操作规范、触发条件和版本",
    category: "平台管理",
  },
  "/employees/integrations": {
    title: "平台能力 · MCP 与工具",
    description: "管理外部连接器、工具发现和员工授权",
    category: "平台管理",
  },
  "/employees/routing": {
    title: "平台能力 · 业务入口与员工路由",
    description: "先绑定入口员工池，再配置意图、优先级和兜底员工",
    category: "平台管理",
  },
  "/employees/route-evaluation": {
    title: "平台能力 · 路由评测集",
    description: "用固定问题回归验证员工分派，量化意图识别准确率",
    category: "平台管理",
  },
  "/employees/supervisor": {
    title: "平台能力 · 主管编排",
    description: "演示复杂任务拆解、能力缺口和跨员工协作",
    category: "平台管理",
  },
  "/employees/drafts": {
    title: "平台能力 · 草案与发布",
    description: "完成评审、试用、评测、发布、回滚和模板沉淀",
    category: "平台管理",
  },
  "/models": {
    title: "平台资源 · 全局模型",
    description: "查看主模型、Embedding、知识排序和回答校验",
    category: "平台管理",
  },
  "/models/employees": {
    title: "平台资源 · 员工模型路由",
    description: "为单个数字员工配置分类、生成、校验和预算",
    category: "平台管理",
  },
  "/models/integrations": {
    title: "平台资源 · 外部集成",
    description: "查看业务系统、工具、存储和任务运行方式",
    category: "平台管理",
  },
  "/knowledge": {
    title: "平台资源 · 知识库总览",
    description: "按任务进入空间、文档、检索、评测和修复页面",
    category: "平台管理",
  },
  "/knowledge/spaces": {
    title: "知识库 · 知识空间",
    description: "管理资料归属、渠道、品类和发布门禁",
    category: "平台管理",
  },
  "/knowledge/documents": {
    title: "知识库 · 知识文档",
    description: "创建文档、维护版本、编辑和归档",
    category: "平台管理",
  },
  "/knowledge/search": {
    title: "知识库 · 检索调试",
    description: "验证数字员工能否命中正确知识",
    category: "平台管理",
  },
  "/knowledge/evaluation": {
    title: "知识库 · 质量评测",
    description: "用固定问题检查召回、排序和拒答质量",
    category: "平台管理",
  },
  "/knowledge/repairs": {
    title: "知识库 · 修复与反馈",
    description: "处理评测失败、线上负反馈和修复回归",
    category: "平台管理",
  },
  "/operations": {
    title: "平台治理 · 运行与审计",
    description: "查看工具调用、模型成本、Trace 和外部同步",
    category: "平台管理",
  },
};

const employeeSections: Record<string, EmployeeSection> = {
  "/employees/roster": "roster",
  "/employees/templates": "templates",
  "/employees/skills": "skills",
  "/employees/integrations": "integrations",
  "/employees/routing": "routing",
  "/employees/route-evaluation": "route-evaluation",
  "/employees/supervisor": "supervisor",
  "/employees/drafts": "drafts",
};

const knowledgeSections: Record<string, KnowledgeSection> = {
  "/knowledge": "overview",
  "/knowledge/spaces": "spaces",
  "/knowledge/documents": "documents",
  "/knowledge/search": "search",
  "/knowledge/evaluation": "evaluation",
  "/knowledge/repairs": "repairs",
};

const ecommerceSections: Record<string, EcommerceSection> = {
  "/ecommerce": "overview",
  "/ecommerce/products": "products",
  "/ecommerce/listings": "listings",
  "/ecommerce/insights": "insights",
};

const modelSections: Record<string, ModelsSection> = {
  "/models": "global",
  "/models/employees": "employees",
  "/models/integrations": "integrations",
};

const customerServiceSections: Record<string, CustomerServiceSection> = {
  "/customer-service": "chat",
  "/customer-service/workbench": "workbench",
  "/customer-service/admin": "admin",
  "/customer-service/approvals": "approvals",
  "/customer-service/incidents": "incidents",
};

const employeePageNavigation = [
  { key: "/employees/roster", label: "员工状态" },
  { key: "/employees/templates", label: "岗位模板" },
  { key: "/employees/skills", label: "Skill（岗位规程）" },
  { key: "/employees/integrations", label: "MCP（业务连接）" },
  { key: "/employees/routing", label: "业务入口与分派" },
  { key: "/employees/route-evaluation", label: "路由评测" },
  { key: "/employees/supervisor", label: "主管编排" },
  { key: "/employees/drafts", label: "上岗审核" },
] as const;

const customerServicePageNavigation = [
  { key: "/customer-service", label: "客服对话" },
  { key: "/customer-service/workbench", label: "人工工作台" },
  { key: "/customer-service/admin", label: "主管看板" },
  { key: "/customer-service/approvals", label: "写操作审批" },
  { key: "/customer-service/incidents", label: "执行异常" },
] as const;

const legacyPagePaths: Record<string, string> = {
  overview: "/overview",
  tickets: "/tickets",
  "customer-service": "/customer-service",
  ecommerce: "/ecommerce",
  employees: "/employees/roster",
  models: "/models",
  knowledge: "/knowledge",
  operations: "/operations",
};

function cleanRouteSearch(searchParams: URLSearchParams): URLSearchParams {
  for (const key of ["page", "mode", "drafts", "jump"]) {
    searchParams.delete(key);
  }
  return searchParams;
}

/**
 * Resolve the path requested by the URL without consulting an identity.
 *
 * The landing path depends on the server capability snapshot, which is not
 * available until ``AuthGate`` finishes ``GET /api/v1/me``. An empty result
 * means "no explicit path"; the component chooses a landing page after auth.
 */
function resolveRequestedPath(): string {
  if (typeof window === "undefined") return "";
  const currentPath = window.location.pathname;
  if (routeMeta[currentPath]) return currentPath;
  const url = new URL(window.location.href);
  if (currentPath === "/employees") {
    url.pathname = "/employees/roster";
    window.history.replaceState({}, document.title, url);
    return "/employees/roster";
  }
  const page = url.searchParams.get("page");
  if (!page) return "";
  let target = legacyPagePaths[page] ?? "";
  if (page === "employees" && url.searchParams.get("mode") === "advanced") {
    target =
      url.searchParams.get("drafts") === "1"
        ? "/employees/drafts"
        : "/employees/skills";
  }
  if (!target) return "";
  url.pathname = target;
  url.search = cleanRouteSearch(url.searchParams).toString();
  window.history.replaceState({}, document.title, url);
  return target;
}

function landingPathFor(hasCapability: (capability: Capability) => boolean): string {
  if (hasCapability("platform.overview")) return "/overview";
  if (hasCapability("service.chat")) return "/customer-service";
  if (hasCapability("operations.view")) return "/operations";
  if (hasCapability("knowledge.view")) return "/knowledge";
  if (
    hasCapability("tickets.view") ||
    hasCapability("tickets.view_self")
  ) {
    return "/tickets";
  }
  return "/demo";
}

function routeForTarget(target: string): string {
  if (target.startsWith("/")) return target;
  if (target === "employees") return "/employees/roster";
  return legacyPagePaths[target] ?? "/customer-service";
}

export default function App() {
  const queryClient = useQueryClient();
  const {
    me,
    roleLabel,
    activeBusinessUnitId,
    activeBusinessUnitLabel,
    capabilities,
    isTestMode,
    testIdentity,
    hasCapability,
    canAccessPath,
  } = useAuth();
  const [activePath, setActivePath] = useState(resolveRequestedPath);
  const [routeRevision, setRouteRevision] = useState(0);
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideStep, setGuideStep] = useState(0);
  const homePath = landingPathFor(hasCapability);
  const current =
    routeMeta[activePath] ?? routeMeta[homePath] ?? routeMeta["/customer-service"];
  const pathAllowed = Boolean(activePath) && canAccessPath(activePath);
  const visibleCustomerServiceNavigation = customerServicePageNavigation.filter(
    (item) => canAccessPath(item.key),
  );
  const visibleEmployeeNavigation = employeePageNavigation.filter((item) =>
    canAccessPath(item.key),
  );

  useEffect(() => {
    if (activePath) return;
    window.history.replaceState({}, document.title, homePath);
    setActivePath(homePath);
  }, [activePath, homePath]);

  useEffect(() => {
    const switchedIdentity = consumeIdentitySwitchNotice();
    if (switchedIdentity) {
      message.success(`已切换为${switchedIdentity}。`);
    }
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const path = routeMeta[window.location.pathname]
        ? window.location.pathname
        : "";
      setActivePath(path);
      setRouteRevision((value) => value + 1);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = (target: string) => {
    const nextPath = routeForTarget(target);
    const targetUrl = new URL(nextPath, window.location.origin);
    const targetPath = targetUrl.pathname;
    if (!routeMeta[targetPath]) return;
    const url = new URL(window.location.href);
    if (
      targetPath === activePath &&
      targetUrl.search === url.search
    ) {
      return;
    }
    url.pathname = targetPath;
    url.search = targetUrl.search;
    window.history.pushState({}, document.title, url);
    setActivePath(targetPath);
    setRouteRevision((value) => value + 1);
  };

  const employeeSection = employeeSections[activePath];
  const knowledgeSection = knowledgeSections[activePath];
  const ecommerceSection = ecommerceSections[activePath];
  const modelSection = modelSections[activePath];
  const customerServiceSection = customerServiceSections[activePath];
  const scenarioChildren = [
    { key: "/customer-service", label: "企业服务台 Agent" },
    { key: "/ecommerce", label: "电商运营复用" },
    { key: "/tickets", label: "内部工单 / HR" },
  ].filter((item) => canAccessPath(item.key));
  const platformChildren = [
    { key: "/employees/roster", label: "员工、Skill 与 MCP" },
    { key: "/knowledge", label: "知识与评测" },
    { key: "/models", label: "模型与连接" },
    { key: "/operations", label: "运行与审计" },
  ].filter((item) => canAccessPath(item.key));
  const scenarioMenu = {
    key: "demo-scenarios",
    label: "Agent 演示",
    children: scenarioChildren,
  };
  const platformMenu = {
    key: "platform-management",
    label: "平台管理",
    children: platformChildren,
  };
  const menuItems = [
    ...(hasCapability("platform.overview")
      ? [{ key: "/overview", label: "平台总览" }]
      : []),
    ...(scenarioMenu.children.length ? [scenarioMenu] : []),
    ...(platformMenu.children.length ? [platformMenu] : []),
  ];

  return (
    <Layout className="app-shell">
      <Sider className="app-sider" width={250} breakpoint="lg" collapsedWidth={0}>
        <div className="app-brand">
          <span className="app-brand-mark">OD</span>
          <div>
            <strong>OnDuty 数字员工平台</strong>
            <span>DIGITAL WORKFORCE DEMO</span>
          </div>
        </div>
        <Menu
          className="app-menu"
          theme="dark"
          mode="inline"
          selectedKeys={[
            employeeSection
              ? "/employees/roster"
              : knowledgeSection
                ? "/knowledge"
                : ecommerceSection
                  ? "/ecommerce"
                  : modelSection
                    ? "/models"
                    : customerServiceSection
                      ? "/customer-service"
                      : activePath,
          ]}
          defaultOpenKeys={[
            "demo-scenarios",
            "platform-management",
          ]}
          onClick={({ key }) => navigate(key)}
          items={menuItems}
        />
        <div className="app-sidebar-footer">
          <Tag color="gold">演示环境</Tag>
          <Text>
            {activeBusinessUnitId} · {activeBusinessUnitLabel}
          </Text>
        </div>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div>
            <Space size={8} wrap>
              <Tag
                color={current.category === "Agent 演示" ? "gold" : "cyan"}
              >
                {current.category}
              </Tag>
              <span className="eyebrow">{current.description}</span>
            </Space>
            <Title level={3} style={{ color: "white", margin: 0 }}>
              {current.title}
            </Title>
          </div>
          <Space wrap>
            <Tag color="cyan">
              {activeBusinessUnitLabel} · {roleLabel}
            </Tag>
            {isTestMode && testIdentity && (
              <>
                {activePath === "/customer-service" ? (
                  <Tag color="cyan">
                    演示视角：
                    {new URLSearchParams(window.location.search).get(
                      "scenario",
                    ) === "ecommerce"
                      ? "买家"
                      : "员工"}
                  </Tag>
                ) : (
                  <Tag color="cyan">
                    当前视角：
                    {demoPerspectiveLabels[testIdentity.id] ??
                      testIdentity.label}
                  </Tag>
                )}
                <Dropdown
                  trigger={["click"]}
                  menu={{
                    selectable: true,
                    selectedKeys: [testIdentity.id],
                    items: testIdentityProfiles.map((profile) => ({
                      key: profile.id,
                      label: `${demoPerspectiveLabels[profile.id] ?? profile.label} · ${profile.description}`,
                    })),
                    onClick: ({ key }) => {
                      window.location.assign(switchTestIdentity(key));
                    },
                  }}
                >
                  <Button size="small" title="切换演示视角">
                    切换视角
                  </Button>
                </Dropdown>
              </>
            )}
            <Button onClick={() => setGuideOpen(true)}>5 步技术演示</Button>
            <Button
              className="header-refresh"
              onClick={() => queryClient.invalidateQueries()}
            >
              刷新数据
            </Button>
          </Space>
        </Header>
        <Content className="app-content">
          {pathAllowed && employeeSection && (
            <Menu
              className="knowledge-subnav"
              mode="horizontal"
              selectedKeys={[activePath]}
              onClick={({ key }) => navigate(key)}
              items={[...visibleEmployeeNavigation]}
            />
          )}
          {pathAllowed && customerServiceSection && (
            <Menu
              className="knowledge-subnav"
              mode="horizontal"
              selectedKeys={[activePath]}
              onClick={({ key }) => navigate(key)}
              items={[...visibleCustomerServiceNavigation]}
            />
          )}
          {!activePath ? (
            <div className="route-loading">
              <Spin size="large" />
            </div>
          ) : !pathAllowed ? (
            <AccessDenied
              roleLabel={roleLabel}
              capabilities={capabilities}
              onBackHome={() => navigate(homePath)}
            />
          ) : (
          <Suspense
            fallback={
              <div className="route-loading">
                <Spin size="large" />
              </div>
            }
          >
            {activePath === "/overview" && (
              <OverviewPage
                key="overview"
                onNavigate={navigate}
                onOpenGuide={() => setGuideOpen(true)}
              />
            )}
            {activePath === "/tickets" && <TicketsPage key="business" />}
            {ecommerceSection && (
              <EcommercePage
                key={`business-${ecommerceSection}`}
                technicalMode={false}
                section={ecommerceSection}
                onNavigate={navigate}
              />
            )}
            {customerServiceSection && (
              <CustomerServicePage
                key={`customer-service-${customerServiceSection}-${routeRevision}`}
                technicalMode={
                  customerServiceSection === "admin" ||
                  customerServiceSection === "approvals" ||
                  customerServiceSection === "incidents"
                }
                section={customerServiceSection}
                onNavigate={navigate}
              />
            )}
            {employeeSection && (
              <EmployeesPage
                key={`employee-${employeeSection}`}
                section={employeeSection}
                advanced={true}
                onNavigate={navigate}
              />
            )}
            {modelSection && (
              <ModelsPage
                section={modelSection}
                onNavigate={navigate}
              />
            )}
            {knowledgeSection && (
              <KnowledgePage
                key={knowledgeSection}
                section={knowledgeSection}
                onNavigate={navigate}
              />
            )}
            {activePath === "/operations" && <OperationsPage />}
          </Suspense>
          )}
        </Content>
      </Layout>
      {guideOpen && (
        <Suspense fallback={null}>
          <DemoGuideDrawer
            step={guideStep}
            onStepChange={setGuideStep}
            onClose={() => setGuideOpen(false)}
            onNavigate={navigate}
          />
        </Suspense>
      )}
    </Layout>
  );
}

