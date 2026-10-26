import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();

const hrEmployee = {
  id: "employee-hr-e2e",
  employee_key: "demo_hr_onboarding",
  name: "HR 入职资料数字员工",
  version: "1.0.0",
  scenario_type: "enterprise_service",
  domain: "human_resources",
  template_code: "hr_onboarding",
  workflow_key: "hr_onboarding_document_collection_v1",
  business_unit_id: "bu_demo",
  service_identity: "digital_employee.hr_onboarding",
  status: "ACTIVE",
  handoff_queue: "HR_SERVICE_DESK",
  knowledge_policy: {},
  model_profile: {},
  tool_allowlist: ["ticket.read", "knowledge.search"],
  manifest: {},
  activation_evaluation: { passed: true, checks: [] },
  activation_evaluated_at: now,
  config_revision: 3,
  instruction: "收集入职材料清单，并提醒候选人补齐缺失文件。",
  created_at: now,
  updated_at: now,
};

const peerEmployee = {
  ...hrEmployee,
  id: "employee-desk-e2e",
  employee_key: "demo_enterprise_desk",
  name: "企业服务台数字员工",
  template_code: "enterprise_service_desk",
  status: "ACTIVE",
  service_identity: "digital_employee.enterprise_desk",
  handoff_queue: "SERVICE_DESK",
};

const enterpriseEntry = {
  id: "entry-enterprise-e2e",
  business_unit_id: "bu_demo",
  code: "enterprise_service_desk",
  name: "企业服务台入口",
  description: "承接 IT、行政和人事请求。",
  domain: "enterprise_service",
  channel: "enterprise_service",
  status: "ACTIVE",
  default_employee_id: peerEmployee.id,
  fallback_employee_id: null,
  human_queue_id: "SERVICE_DESK",
  knowledge_scope: {},
  sla_policy: {},
  employees: [
    {
      employee_id: peerEmployee.id,
      employee_key: peerEmployee.employee_key,
      employee_name: peerEmployee.name,
      role_type: "PRIMARY",
      priority: 10,
      enabled: true,
      employee_status: peerEmployee.status,
    },
    {
      employee_id: hrEmployee.id,
      employee_key: hrEmployee.employee_key,
      employee_name: hrEmployee.name,
      role_type: "SPECIALIST",
      priority: 20,
      enabled: true,
      employee_status: hrEmployee.status,
    },
  ],
  version: 1,
  created_at: now,
  updated_at: now,
};

const hrEntry = {
  ...enterpriseEntry,
  id: "entry-hr-e2e",
  code: "internal_hr_service",
  name: "内部 HR 服务入口",
  description: "承接入职、转正、离职、假期和人事资料请求。",
  default_employee_id: hrEmployee.id,
  human_queue_id: "HR_SERVICE_DESK",
  employees: [
    {
      employee_id: hrEmployee.id,
      employee_key: hrEmployee.employee_key,
      employee_name: hrEmployee.name,
      role_type: "PRIMARY",
      priority: 10,
      enabled: true,
      employee_status: hrEmployee.status,
    },
  ],
};

const knowledgeSpace = {
  id: "space-hr-e2e",
  business_unit_id: "bu_demo",
  code: "hr_onboarding_knowledge",
  name: "HR 入职知识库",
  description: "入职材料清单与常见问题",
  domain: "human_resources",
  channel: "enterprise_service",
  category: null,
  category_profile_id: null,
  workflow_key: "hr_onboarding_document_collection_v1",
  owner_id: "e2e-agent",
  evaluation_required: true,
  status: "ACTIVE",
  document_count: 3,
  created_at: now,
  updated_at: now,
};

const knowledgeBinding = {
  id: "binding-knowledge-e2e",
  employee_id: hrEmployee.id,
  knowledge_space_id: knowledgeSpace.id,
  workflow_key: "hr_onboarding_document_collection_v1",
  scope: {},
  enabled: true,
  created_at: now,
  updated_at: now,
};

const skillBinding = {
  id: "binding-skill-e2e",
  employee_id: hrEmployee.id,
  skill_id: "skill-hr-e2e",
  skill_code: "hr-onboarding-documents",
  skill_name: "入职材料核验",
  enabled: true,
  priority: 10,
};

const mcpBinding = {
  id: "binding-mcp-e2e",
  employee_id: hrEmployee.id,
  connector_id: "mcp-hr-e2e",
  connector_code: "hr-records",
  connector_name: "HR 档案系统",
  enabled: true,
  allowed_tools: ["employee.get", "document.check"],
  write_approved: false,
};

const routeRule = {
  id: "rule-hr-e2e",
  business_unit_id: "bu_demo",
  employee_id: hrEmployee.id,
  intents: ["入职", "转正", "人事"],
  categories: [],
  channels: [],
  priority: 20,
  fallback: false,
  enabled: true,
  updated_at: now,
};

async function mockEmployeeApis(page: Page): Promise<void> {
  await page.route(
    "**/api/v1/digital-employees?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([hrEmployee, peerEmployee]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-templates?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    },
  );
  await page.route(
    "**/api/v1/business-service-entries?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([enterpriseEntry, hrEntry]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge-spaces?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([knowledgeSpace]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/*/knowledge-bindings",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([knowledgeBinding]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/*/skills",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([skillBinding]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/*/mcp-connectors",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([mcpBinding]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-route-rules?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([routeRule]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-route-decisions?**",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
}

test("员工名单可看到服务入口和跨入口复用标识", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockEmployeeApis(page);
  await page.goto("/employees/roster");

  const row = page
    .getByRole("row", { name: new RegExp(hrEmployee.name) });
  await expect(row).toBeVisible();
  await expect(row.getByText("企业服务台入口")).toBeVisible();
  await expect(row.getByText("内部 HR 服务入口")).toBeVisible();
  await expect(row.getByText("跨入口复用")).toBeVisible();
});

test("名单姓名可打开员工能力快照并显示复用入口与资源", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockEmployeeApis(page);
  await page.goto("/employees/roster");

  await page
    .getByRole("button", { name: hrEmployee.name, exact: true })
    .click();
  const drawer = page.locator(".ant-drawer-content");
  await expect(
    drawer.getByText(`员工快照 · ${hrEmployee.name}`),
  ).toBeVisible();
  await expect(drawer.getByText("跨入口复用")).toBeVisible();
  await expect(drawer.getByText("企业服务台入口")).toBeVisible();
  await expect(drawer.getByText("内部 HR 服务入口")).toBeVisible();
  await expect(drawer.getByText("入职材料核验")).toBeVisible();
  await expect(drawer.getByText("HR 入职知识库")).toBeVisible();
  await expect(drawer.getByText("HR 档案系统")).toBeVisible();
  await expect(drawer.getByText("employee.get")).toBeVisible();
});

test("员工深链 ?employee= 可直接打开能力快照", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockEmployeeApis(page);
  await page.goto(`/employees/roster?employee=${hrEmployee.id}`);

  const drawer = page.locator(".ant-drawer-content");
  await expect(
    drawer.getByText(`员工快照 · ${hrEmployee.name}`),
  ).toBeVisible();
  await expect(drawer.getByText("2 个服务入口")).toBeVisible();
});

test("业务入口与分派页标记跨入口复用员工", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockEmployeeApis(page);
  await page.goto("/employees/routing");

  await expect(page.getByText("1 名员工跨入口复用")).toHaveCount(2);
  await expect(
    page.getByText(`${hrEmployee.name} · 专业 · 复用 2 个入口`),
  ).toBeVisible();
  await expect(
    page.getByText(`${hrEmployee.name} · 默认 · 复用 2 个入口`),
  ).toBeVisible();
});
