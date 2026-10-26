import { expect, test } from "@playwright/test";

test("新建 Skill 按钮提交完整规程配置", async ({ page }) => {
  await page.route(
    "**/api/v1/skills?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/skills"),
  );
  await page.route("**/api/v1/skills", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "e2e-skill",
        code: "e2e-skill",
        name: "E2E 客服规程",
        instructions: "先查知识，再回答。",
        triggers: ["材质"],
        tools: ["knowledge.search"],
        status: "ACTIVE",
        version: 1,
      }),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/employees/skills");
  await page.getByRole("button", { name: "新建 Skill" }).click();
  const dialog = page.getByRole("dialog", { name: "新建 Skill" });
  await dialog.getByPlaceholder("ecommerce-presales").fill("e2e-skill");
  await dialog.locator("input").nth(1).fill("E2E 客服规程");
  await dialog
    .getByPlaceholder("说明执行步骤、事实来源、禁止行为和人工升级条件。")
    .fill("先检索商品知识，再按资料回答。");
  await dialog.getByRole("button", { name: /^保\s*存$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    code: "e2e-skill",
    name: "E2E 客服规程",
    instructions: "先检索商品知识，再按资料回答。",
  });
});

const connector = {
  id: "e2e-mcp-connector",
  business_unit_id: "bu_demo",
  code: "e2e-mcp",
  name: "E2E MCP",
  description: "E2E MCP connector",
  transport: "streamable_http",
  url: "https://mcp.example.com/mcp",
  header_env: {},
  timeout_seconds: 30,
  status: "ACTIVE",
  tools: [],
  last_checked_at: null,
  last_check_error: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

async function mockMcpList(
  page: import("@playwright/test").Page,
  items: unknown[],
): Promise<void> {
  await page.route(
    "**/api/v1/mcp/connectors?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(items),
      });
    },
  );
}

test("新建 MCP 连接器按钮提交连接配置", async ({ page }) => {
  await mockMcpList(page, []);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/mcp/connectors"),
  );
  await page.route("**/api/v1/mcp/connectors", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(connector),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/employees/integrations");
  await page.getByRole("button", { name: "新建 MCP 连接器" }).click();
  const dialog = page.getByRole("dialog", {
    name: "新建 MCP 连接器",
  });
  await dialog.getByPlaceholder("order-center").fill("e2e-mcp");
  await dialog.locator("input").nth(1).fill("E2E MCP");
  await dialog
    .getByPlaceholder("https://mcp.example.com/mcp")
    .fill("https://mcp.example.com/mcp");
  await dialog.getByRole("button", { name: /^保\s*存$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    code: "e2e-mcp",
    name: "E2E MCP",
    transport: "streamable_http",
    url: "https://mcp.example.com/mcp",
  });
});

test("MCP 测试发现按钮调用健康检查", async ({ page }) => {
  await mockMcpList(page, [connector]);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/api/v1/mcp/connectors/${connector.id}/discover`,
      ),
  );
  await page.route(
    `**/api/v1/mcp/connectors/${connector.id}/discover`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          connector_id: connector.id,
          healthy: true,
          tool_count: 2,
          tools: [],
          error: null,
          checked_at: new Date().toISOString(),
        }),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/employees/integrations");
  await expect(page.getByText("E2E MCP", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "测试/发现" }).click();
  await requestPromise;
});
