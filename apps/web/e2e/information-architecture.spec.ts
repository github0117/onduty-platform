import { expect, test } from "@playwright/test";

test("侧边栏只保留 Agent 演示和平台管理，员工二级页面使用页内导航", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/overview");
  await expect(page.getByText("Agent 演示", { exact: true })).toBeVisible();
  await expect(page.getByText("平台管理", { exact: true })).toBeVisible();
  await page.getByText("员工、Skill 与 MCP", { exact: true }).click();
  await expect(page).toHaveURL(/\/employees\/roster$/);
  await expect(
    page.getByText("Skill 与 MCP 属于员工能力配置", {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByText("Skill（岗位规程）", { exact: true }).click();
  await expect(page).toHaveURL(/\/employees\/skills$/);
  await expect(
    page.getByRole("heading", {
      name: "Skill · 岗位操作规程",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByText("MCP（业务连接）", { exact: true }).click();
  await expect(page).toHaveURL(/\/employees\/integrations$/);
  await expect(
    page.getByRole("heading", {
      name: "MCP · 业务系统连接",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("主管编排", { exact: true }),
  ).toBeVisible();
});

test("演示视角和业务单元统一收进 5 步演示设置", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/overview");

  await expect(
    page.getByText("当前视角：平台管理员", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "切换演示视角" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "切换业务单元" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "5 步技术演示" }).click();
  await expect(
    page.getByText("演示业务单元", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "切换演示视角" }),
  ).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "切换业务单元" }),
  ).toBeVisible();
});

test("5 步演示中的视角菜单可切换角色并进入对应首页", async ({ page }) => {
  await page.goto("/overview");

  await page.getByRole("button", { name: "5 步技术演示" }).click();
  await expect(
    page.getByText("不同视角用于展示权限边界", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".ant-select")
    .filter({
      has: page.locator('input[aria-label="切换演示视角"]'),
    })
    .click();
  await expect(
    page.getByText("业务执行者 · 处理客户服务和接管会话", {
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByText("业务执行者 · 处理客户服务和接管会话", {
      exact: true,
    })
    .click();

  await expect(page).toHaveURL(/\/customer-service\/workbench$/);
  await expect(
    page.getByText("当前视角：业务执行者", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("已切换为客服坐席。", { exact: true }),
  ).toBeVisible();
});

test("客服聊天明确区分操作人和对话双方并适配平板与手机", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "service-agent",
    );
  });
  await page.goto("/customer-service?scenario=ecommerce");

  await expect(
    page.getByRole("combobox", { name: "切换演示视角" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("演示视角：买家", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("当前视角", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("模拟买家", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByText("这段对话里", { exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByText(/你（模拟买家）.*由业务入口自动分派/)
      .first(),
  ).toBeVisible();

  const columns = await page.locator(".chat-demo-grid").evaluate(
    (element) =>
      window.getComputedStyle(element).gridTemplateColumns.split(" ").length,
  );
  expect(columns).toBe(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const headingBox = await page
    .getByRole("heading", { name: "像买家一样问，像客服一样答" })
    .boundingBox();
  expect(headingBox?.x ?? 0).toBeGreaterThan(0);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("客服坐席测试身份不显示平台管理菜单", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "service-agent",
    );
    window.localStorage.setItem(
      "digital-workforce:test-business-unit",
      "bu_demo",
    );
  });
  await page.goto("/overview");
  await expect(page.getByText("Agent 演示", { exact: true })).toBeVisible();
  await expect(page.getByText("平台管理", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("当前视角：业务执行者", { exact: true }),
  ).toBeVisible();
});

test("业务经理测试身份只看到业务演示和审批审计", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "business-manager",
    );
    window.localStorage.setItem(
      "digital-workforce:test-business-unit",
      "bu_demo",
    );
  });
  await page.goto("/overview");
  await expect(page.getByText("平台管理", { exact: true })).toBeVisible();
  await expect(
    page.getByText("运行与审计", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("员工、Skill 与 MCP", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("当前视角：管理者", { exact: true }),
  ).toBeVisible();
});

test("切换业务单元后 API 查询和身份头同步切换", async ({ page }) => {
  let observedUrl = "";
  let observedBusinessUnit = "";
  await page.route("**/api/v1/metrics/rag?*", async (route) => {
    observedUrl = route.request().url();
    observedBusinessUnit =
      route.request().headers()["x-business-unit-id"] ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        draft_count: 0,
        grounded_count: 0,
        no_knowledge_count: 0,
        citation_total: 0,
        average_citations: 0,
        grounding_rate: 0,
        claim_count: 0,
        cited_claim_count: 0,
        policy_claim_count: 0,
        policy_citation_coverage: 0,
        semantic_verified_claim_count: 0,
        citation_coverage: 0,
        unsupported_claim_count: 0,
        judge_provider: "local",
        judge_model: "rule",
        judge_calls: 0,
      }),
    });
  });
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "platform-admin",
    );
    window.localStorage.setItem(
      "digital-workforce:test-business-unit",
      "bu_acceptance",
    );
  });
  await page.goto("/overview");
  await expect.poll(() => observedBusinessUnit).toBe("bu_acceptance");
  expect(observedUrl).toContain("business_unit_id=bu_acceptance");
});

test("能力总览展示一条主演示和三个复用案例", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "service-agent",
    );
  });
  await page.goto("/overview");
  await expect(
    page.getByRole("heading", {
      name: "一条主演示 + 三个复用案例",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("先主链，后复用", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("技术验收证据", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("技术实现主线", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("电商客服复用案例", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("电商运营复用案例", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("内部工单与 HR 复用案例", { exact: true }),
  ).toBeVisible();
});

test("电商内容拆分后可直达商品、上架和运营页面", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/ecommerce");
  await expect(
    page.getByRole("heading", {
      name: "电商运营数字员工工作区",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "新增商品" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "进入商品管理" }).click();
  await expect(page).toHaveURL(/\/ecommerce\/products$/);
  await expect(
    page.getByRole("button", { name: "新增商品" }),
  ).toBeVisible();

  await page.goto("/ecommerce/listings");
  await expect(
    page.getByRole("heading", {
      name: /上架审核.*人工与数字员工协作/,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "创建上架任务" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "新增商品" }),
  ).toHaveCount(0);

  await page.goto("/ecommerce/insights");
  await expect(
    page.getByText("发布成功率", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "创建上架任务" }),
  ).toHaveCount(0);
});

test("模型与集成拆分为全局、员工和外部集成页面", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/models");
  await expect(page.getByText("主模型", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "配置模型" }),
  ).toHaveCount(0);

  await page.goto("/models/employees");
  await expect(
    page.getByText("员工模型路由", { exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "配置模型" }).first(),
  ).toBeVisible();

  await page.goto("/models/integrations");
  await expect(page.getByText("外部集成", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("主模型", { exact: true })).toHaveCount(0);
});

test("客服聊天、工作台、审批和事故均有独立入口", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/customer-service");
  await expect(
    page.getByRole("heading", {
      name: "像研发同事一样问，像 Agent 一样执行",
    }),
  ).toBeVisible();

  await page.goto("/customer-service/workbench");
  await expect(
    page.getByRole("heading", {
      name: "人工客服工作台",
      exact: true,
    }),
  ).toBeVisible();

  await page.goto("/customer-service/admin");
  await expect(
    page.getByText("这里演示的是客户服务沙盒", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/企业消息渠道与外部业务系统消息渠道均未连接生产系统/),
  ).toBeVisible();
  await expect(page.getByText(/电商平台消息渠道/)).toHaveCount(0);
  await expect(
    page.getByText("这三个页面分别做什么", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "运营看板：看整体结果、趋势、告警和待接管排队，不处理具体会话。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText("客户服务测试入口", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("会话列表", { exact: true }),
  ).toHaveCount(0);

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByRole("heading", { name: "待审批操作", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "执行异常", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("会话列表", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("客户服务测试入口", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("企业服务台", { exact: true }),
  ).toHaveCount(0);

  await page.goto("/customer-service/incidents");
  await expect(
    page.getByRole("heading", { name: "执行异常", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "待审批操作", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("会话列表", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("客户服务测试入口", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("企业服务台", { exact: true }),
  ).toHaveCount(0);
});

test("通用平台页面不再把电商作为默认业务场景", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/overview");
  await expect(
    page.getByText("企业业务数据", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("外部电商平台真实业务接口", { exact: true }),
  ).toHaveCount(0);

  await page.goto("/models/integrations");
  await expect(
    page.getByText(
      "连接企业服务、客户服务、订单履约和内容运营等外部业务系统。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "连接订单、物流、工单和电商等外部业务系统。",
      { exact: true },
    ),
  ).toHaveCount(0);

  await page.goto("/employees/integrations");
  await expect(
    page.getByText(
      "管理客户、订单、工单等外部系统的连接、工具发现和员工授权。",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "管理订单、物流等外部系统的查询和操作权限。",
      { exact: true },
    ),
  ).toHaveCount(0);
});
