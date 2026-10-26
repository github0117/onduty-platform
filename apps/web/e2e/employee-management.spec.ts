import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();

const employee = {
  id: "employee-e2e",
  employee_key: "e2e_after_sales",
  name: "E2E 售后专员",
  version: "1.0.0",
  scenario_type: "customer_service_ticket",
  domain: "ecommerce",
  template_code: "ecommerce_aftersales",
  workflow_key: "customer_service_ticket_v1",
  business_unit_id: "bu_demo",
  service_identity: "digital_employee.e2e_after_sales",
  status: "TRIAL",
  handoff_queue: "AFTER_SALES_REVIEW",
  knowledge_policy: { default_scope: { workflow: "customer_service_ticket_v1" } },
  model_profile: {
    knowledge: { top_k: 5, min_score: 0.15 },
    budgets: { daily_cost: 2, weekly_cost: 10, monthly_cost: 30 },
  },
  tool_allowlist: ["ticket.read", "knowledge.search", "draft.create"],
  manifest: {},
  activation_evaluation: {
    passed: false,
    checks: [],
  },
  activation_evaluated_at: null,
  config_revision: 1,
  created_at: now,
  updated_at: now,
};

const template = {
  id: "template-e2e",
  code: "ecommerce_aftersales",
  name: "电商售后专员模板",
  description: "处理退款、退货与物流异常。",
  domain: "ecommerce",
  workflow_key: "customer_service_ticket_v1",
  scenario_type: "customer_service_ticket",
  handoff_queue: "AFTER_SALES_REVIEW",
  capabilities: ["售后核验", "退款建议"],
  intents: ["退款", "退货"],
  skill_codes: ["ecommerce-aftersales"],
  tool_allowlist: ["ticket.read", "knowledge.search", "draft.create"],
  status: "PUBLISHED",
  builtin: true,
  source_draft_id: null,
  version: 1,
  published_at: now,
  knowledge_bindings: [],
  mcp_bindings: [],
  model_profile: {},
  knowledge_policy: {},
  readiness_snapshot: {},
};

const skill = {
  id: "skill-e2e",
  business_unit_id: "bu_demo",
  code: "ecommerce-aftersales",
  name: "售后退款规程",
  description: "核验订单与退款资格",
  instructions: "先读取订单，再检索售后政策，最后生成人工审核草稿。",
  triggers: ["退款", "退货"],
  tools: ["knowledge.search", "ticket.read"],
  status: "ACTIVE",
  version: 2,
  created_by: "e2e-agent",
  created_at: now,
  updated_at: now,
};

const connector = {
  id: "mcp-e2e",
  business_unit_id: "bu_demo",
  code: "e2e-orders",
  name: "E2E 订单中心",
  description: "订单与物流只读查询",
  transport: "streamable_http",
  url: "https://mcp.example.com/mcp",
  header_env: { Authorization: "E2E_MCP_TOKEN" },
  timeout_seconds: 30,
  status: "ACTIVE",
  tools: [
    {
      name: "orders.get",
      description: "查询订单",
      input_schema: {},
      is_write: false,
    },
  ],
  last_checked_at: now,
  last_check_error: null,
  created_at: now,
  updated_at: now,
};

const space = {
  id: "space-e2e",
  business_unit_id: "bu_demo",
  code: "e2e_after_sales",
  name: "E2E 售后知识",
  description: "售后规则",
  domain: "ecommerce",
  channel: "ecommerce_demo",
  category: "保温杯",
  category_profile_id: null,
  workflow_key: "customer_service_ticket_v1",
  owner_id: "e2e-agent",
  evaluation_required: true,
  status: "ACTIVE",
  document_count: 2,
  created_at: now,
  updated_at: now,
};

const routeRule = {
  id: "route-rule-e2e",
  business_unit_id: "bu_demo",
  employee_id: employee.id,
  intents: ["退款", "退货"],
  categories: ["保温杯"],
  channels: ["ecommerce_demo"],
  priority: 10,
  fallback: false,
  enabled: true,
  updated_at: now,
};

const businessEntry = {
  id: "entry-e2e",
  business_unit_id: "bu_demo",
  code: "ecommerce_customer_service",
  name: "国内电商客服入口",
  description: "承接商品、物流和售后问题",
  domain: "ecommerce",
  channel: "web_form",
  status: "ACTIVE",
  default_employee_id: employee.id,
  fallback_employee_id: null,
  human_queue_id: "ECOMMERCE_SERVICE_HUMAN",
  knowledge_scope: {},
  sla_policy: {},
  employees: [
    {
      employee_id: employee.id,
      employee_key: employee.employee_key,
      employee_name: employee.name,
      role_type: "PRIMARY",
      priority: 10,
      enabled: true,
      employee_status: employee.status,
    },
  ],
  version: 1,
  created_at: now,
  updated_at: now,
};

async function mockEmployeeShell(
  page: Page,
  employees = [employee],
): Promise<void> {
  await page.route(
    "**/api/v1/digital-employees?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(employees),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-templates?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([template]),
      });
    },
  );
}

async function openPage(page: Page, path: string): Promise<void> {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto(path);
}

test("新建数字员工按钮提交岗位标识、工作流和人工队列", async ({
  page,
}) => {
  await mockEmployeeShell(page, []);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/digital-employees"),
  );
  await page.route("**/api/v1/digital-employees", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ ...employee, id: "employee-created" }),
    });
  });
  await openPage(page, "/employees/roster");
  await page.getByRole("button", { name: "新建数字员工" }).click();
  const dialog = page.getByRole("dialog", { name: "新建数字员工" });
  await dialog.locator(".ant-input").nth(0).fill("E2E 新建员工");
  await dialog.locator(".ant-input").nth(1).fill("e2e_new_employee");
  await dialog.getByRole("button", { name: /^创\s*建$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    employee_key: "e2e_new_employee",
    name: "E2E 新建员工",
    workflow_key: "customer_service_ticket_v1",
    handoff_queue: "MANUAL_TRIAGE",
    business_unit_id: "bu_demo",
  });
  await expect(page.getByText("数字员工已创建")).toBeVisible();
});

test("从模板创建员工自动继承资源并提交知识空间", async ({ page }) => {
  await mockEmployeeShell(page, []);
  await page.route(
    "**/api/v1/knowledge-spaces?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([space]),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/digital-employees/from-template"),
  );
  await page.route(
    "**/api/v1/digital-employees/from-template",
    async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ ...employee, status: "TRIAL" }),
      });
    },
  );
  await openPage(page, "/employees/templates");
  await expect(
    page.getByRole("button", { name: "从模板创建" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "使用这个模板" }).click();
  const dialog = page.getByRole("dialog", {
    name: "创建 · 电商售后专员模板",
  });
  await dialog.locator(".ant-input").first().fill("E2E 模板售后员工");
  await dialog.locator(".ant-select").click();
  await page.getByText("E2E 售后知识 · e2e_after_sales", { exact: true }).last().click();
  await dialog
    .getByPlaceholder(/例如：先确认订单号/)
    .fill("E2E 模板提示词");
  await dialog.getByRole("button", { name: "创建员工" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    name: "E2E 模板售后员工",
    template_code: "ecommerce_aftersales",
    business_unit_id: "bu_demo",
    knowledge_space_ids: [space.id],
    instruction: "E2E 模板提示词",
  });
  await expect(
    page.getByText("试用员工已创建，请完成资源检查后评估激活"),
  ).toBeVisible();
});

test("员工配置保存按钮提交知识、Skill、MCP 和预算快照", async ({
  page,
}) => {
  await mockEmployeeShell(page);
  await page.route(
    "**/api/v1/knowledge-spaces?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([space]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/knowledge-bindings",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/skills?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([skill]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/skills",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/mcp/connectors?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([connector]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/mcp-connectors",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/metrics/models/budget?employee_id=employee-e2e",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          employee_id: employee.id,
          business_unit_id: "bu_demo",
          exceeded: false,
          forecast_alert: false,
          periods: [],
        }),
      });
    },
  );
  let savedProfile: Record<string, unknown> = {};
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith(
        "/api/v1/digital-employees/employee-e2e/configuration",
      ),
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/configuration",
    async (route) => {
      savedProfile = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...employee, status: "TRIAL" }),
      });
    },
  );
  await openPage(page, "/employees/roster?mode=advanced");
  await page.getByRole("button", { name: "配置" }).click();
  const drawer = page.getByRole("dialog", { name: "配置 · E2E 售后专员" });
  await expect(
    drawer.getByText("Skill（岗位规程）", { exact: true }),
  ).toBeVisible();
  await expect(
    drawer.getByText("MCP（业务工具）", { exact: true }),
  ).toBeVisible();
  await drawer.locator(".ant-input").first().fill("E2E 售后专员升级版");
  await drawer
    .getByPlaceholder(/例如：你是一名耐心、简洁的售后客服/)
    .fill("E2E 角色提示词");
  await drawer.getByRole("button", { name: "保存配置" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    name: "E2E 售后专员升级版",
    handoff_queue: "AFTER_SALES_REVIEW",
    instruction: "E2E 角色提示词",
    tool_allowlist: ["ticket.read", "knowledge.search", "draft.create"],
  });
  expect(savedProfile.name).toBe("E2E 售后专员升级版");
  await expect(page.getByText("数字员工配置已保存")).toBeVisible();
});

test("试用员工评估并激活成功后刷新状态", async ({ page }) => {
  await mockEmployeeShell(page);
  let active = false;
  await page.route(
    "**/api/v1/digital-employees?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { ...employee, status: active ? "ACTIVE" : "TRIAL" },
        ]),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/digital-employees/employee-e2e/activate",
      ),
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/activate",
    async (route) => {
      active = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...employee, status: "ACTIVE" }),
      });
    },
  );
  await openPage(page, "/employees/roster");
  await page.getByRole("button", { name: "评估并激活" }).click();
  await requestPromise;
  await expect(page.getByText("员工评测通过并已激活")).toBeVisible();
  await expect(page.getByText("启用", { exact: true })).toBeVisible();
});

test("编辑 Skill 保存更新后的规程", async ({ page }) => {
  await mockEmployeeShell(page);
  await page.route(
    "**/api/v1/skills?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([skill]),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith("/api/v1/skills/skill-e2e"),
  );
  await page.route("**/api/v1/skills/skill-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...skill, name: "售后退款规程升级版" }),
    });
  });
  await openPage(page, "/employees/skills");
  await page.getByRole("button", { name: /^编\s*辑$/ }).click();
  const dialog = page.getByRole("dialog", {
    name: "编辑 Skill · ecommerce-aftersales",
  });
  await dialog.locator(".ant-input").nth(1).fill("售后退款规程升级版");
  await dialog.locator("textarea").nth(0).fill("退款,退货,破损");
  await dialog.getByRole("button", { name: /^保\s*存$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    name: "售后退款规程升级版",
    triggers: ["退款", "退货", "破损"],
  });
  await expect(page.getByText("Skill 已更新")).toBeVisible();
});

test("编辑 MCP 连接器保存 URL、环境变量和状态", async ({ page }) => {
  await mockEmployeeShell(page);
  await page.route(
    "**/api/v1/mcp/connectors?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([connector]),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith("/api/v1/mcp/connectors/mcp-e2e"),
  );
  await page.route("**/api/v1/mcp/connectors/mcp-e2e", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...connector, name: "E2E 订单中心升级版" }),
    });
  });
  await openPage(page, "/employees/integrations");
  await page.getByRole("button", { name: /^编\s*辑$/ }).click();
  const dialog = page.getByRole("dialog", {
    name: "编辑 MCP · e2e-orders",
  });
  await dialog.locator(".ant-input").nth(1).fill("E2E 订单中心升级版");
  await dialog.locator("textarea").fill(
    "Authorization=E2E_MCP_TOKEN\nX-Tenant=E2E_TENANT",
  );
  await dialog.getByRole("button", { name: /^保\s*存$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    name: "E2E 订单中心升级版",
    header_env: {
      Authorization: "E2E_MCP_TOKEN",
      "X-Tenant": "E2E_TENANT",
    },
    status: "ACTIVE",
  });
  await expect(page.getByText("MCP 连接器已更新")).toBeVisible();
});

test("业务入口员工池可以单独维护", async ({ page }) => {
  await mockEmployeeShell(page);
  await page.route(
    "**/api/v1/business-service-entries?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([businessEntry]),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-route-rules?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith(
        "/api/v1/business-service-entries/entry-e2e/employees",
      ),
  );
  await page.route(
    "**/api/v1/business-service-entries/entry-e2e/employees",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(businessEntry),
      });
    },
  );
  await openPage(page, "/employees/routing");

  await expect(
    page.getByText("国内电商客服入口", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "配置员工池" }).click();
  await expect(
    page.getByRole("dialog", {
      name: "配置员工池 · 国内电商客服入口",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "保存员工池" }).click();

  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual([
    {
      employee_id: employee.id,
      role_type: "PRIMARY",
      priority: 10,
      enabled: true,
    },
  ]);
});

test("编辑自动路由规则保存意图、优先级和兜底状态", async ({ page }) => {
  await mockEmployeeShell(page);
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
    "**/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PUT" &&
      request.url().endsWith(
        "/api/v1/digital-employees/employee-e2e/route-rule",
      ),
  );
  await page.route(
    "**/api/v1/digital-employees/employee-e2e/route-rule",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(routeRule),
      });
    },
  );
  await openPage(page, "/employees/routing");
  await page.getByRole("button", { name: "编辑路由" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑数字员工路由" });
  await dialog.locator("textarea").fill("退款，退货，商品破损");
  await dialog.getByRole("spinbutton").fill("5");
  await dialog.getByRole("checkbox", { name: "无匹配时使用" }).check();
  await dialog.getByRole("button", { name: "保存路由" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    intents: ["退款", "退货", "商品破损"],
    categories: ["保温杯"],
    channels: ["ecommerce_demo"],
    priority: 5,
    fallback: true,
    enabled: true,
  });
  await expect(page.getByText("数字员工路由已保存")).toBeVisible();
});

test("路由结果使用员工姓名和中文原因，不直接暴露内部状态", async ({
  page,
}) => {
  await mockEmployeeShell(page);
  await page.route(
    "**/api/v1/digital-employee-route-rules?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-route-decisions?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: 1,
          items: [
            {
              id: "route-decision-e2e",
              business_unit_id: "bu_demo",
              ticket_id: null,
              conversation_id: null,
              selected_employee_id: "employee-enterprise",
              selected_employee_key: "enterprise_service_desk_internal",
              candidates: [
                {
                  employee_id: "employee-enterprise",
                  employee_key: "enterprise_service_desk_internal",
                  employee_name: "企业服务台数字员工",
                  status: "ACTIVE",
                  eligible: true,
                  excluded_reasons: [],
                  score: 0.55,
                  keyword_score: 0.5,
                  semantic_score: 0.4,
                  matched_intents: ["制度", "权限"],
                  matched_direct_terms: ["制度", "权限"],
                  matched_subject_terms: ["制度"],
                  matched_body_terms: ["权限"],
                  matched_synonyms: [],
                  fallback: false,
                  selected: true,
                },
                {
                  employee_id: "employee-hr",
                  employee_key: "hr_internal",
                  employee_name: "HR 入职资料数字员工",
                  status: "EVALUATION_FAILED",
                  eligible: false,
                  excluded_reasons: ["员工状态为 EVALUATION_FAILED"],
                  score: 0.2,
                  selected: false,
                },
                {
                  employee_id: "employee-channel",
                  employee_key: "channel_limited_internal",
                  employee_name: "渠道受限员工",
                  status: "ACTIVE",
                  eligible: false,
                  excluded_reasons: [
                    '渠道 web_form 不在规则范围 ["ecommerce_demo"]',
                  ],
                  score: 0.1,
                  selected: false,
                },
              ],
              reason_code: "INTENT_MATCH",
              reason: "Matched intents: 制度,权限",
              score: 0.55,
              confidence: 0.55,
              created_at: now,
            },
          ],
        }),
      });
    },
  );
  await openPage(page, "/employees/routing");

  const row = page
    .locator("tr")
    .filter({ hasText: "企业服务台数字员工" })
    .first();
  await expect(row).toContainText("任务编排");
  await expect(row).toContainText("命中派单依据：制度、权限");
  await expect(row).toContainText("55%");
  await expect(row).not.toContainText("enterprise_service_desk_internal");
  await expect(page.getByText(/Matched intents/)).toHaveCount(0);

  await row.locator(".ant-table-row-expand-icon").click();
  await expect(
    page.getByText("员工状态：评测未通过", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("当前渠道不在派发规则范围内", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/EVALUATION_FAILED/)).toHaveCount(0);
});
