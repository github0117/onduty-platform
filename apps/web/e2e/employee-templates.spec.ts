import { expect, test, type Page } from "@playwright/test";

const templateId = "e2e-managed-template";
const templateName = "E2E 财务审核模板";

const template = {
  id: templateId,
  code: "e2e_finance_review",
  name: templateName,
  description: "E2E 自定义岗位模板",
  domain: "finance",
  workflow_key: "customer_service_ticket_v1",
  scenario_type: "customer_service_ticket",
  handoff_queue: "FINANCE_REVIEW",
  capabilities: ["退款审核"],
  intents: ["退款审核"],
  skill_codes: [],
  tool_allowlist: ["ticket.read"],
  status: "DRAFT",
  builtin: false,
  source_draft_id: "e2e-source-draft",
  version: 1,
  published_at: null,
  knowledge_bindings: [],
  mcp_bindings: [],
  model_profile: {},
  knowledge_policy: {},
  readiness_snapshot: {},
};

async function mockManagedTemplate(
  page: Page,
  status = "DRAFT",
): Promise<void> {
  const current = { ...template, status };
  await page.route(
    "**/api/v1/digital-employee-templates?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(status === "PUBLISHED" ? [current] : []),
      });
    },
  );
  await page.route(
    "**/api/v1/digital-employee-templates/managed?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([current]),
      });
    },
  );
  await page.route(
    `**/api/v1/digital-employee-templates/${templateId}/revisions`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  for (const action of [
    "review",
    "publish",
    "rollback",
    "reopen",
  ]) {
    await page.route(
      `**/api/v1/digital-employee-templates/${templateId}/${action}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(current),
        });
      },
    );
  }
}

test("岗位模板批准按钮提交 APPROVE", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page);
  await page.goto("/employees/templates");
  await expect(page.getByText(templateName, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "批准模板" }).click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/review`,
      ),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  expect((await requestPromise).postDataJSON()).toMatchObject({
    decision: "APPROVE",
  });
});

test("岗位模板拒绝按钮提交 REJECT", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page);
  await page.goto("/employees/templates");
  await page.getByRole("button", { name: "拒绝模板" }).click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/review`,
      ),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  expect((await requestPromise).postDataJSON()).toMatchObject({
    decision: "REJECT",
  });
});

test("已批准模板可以发布", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page, "APPROVED");
  await page.goto("/employees/templates");
  await page.getByRole("button", { name: "发布模板" }).click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/publish`,
      ),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  await requestPromise;
});

test("已发布模板可以停用", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page, "PUBLISHED");
  await page.goto("/employees/templates");
  await page.getByRole("button", { name: "停用模板" }).click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/rollback`,
      ),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  await requestPromise;
});

test("已发布自定义模板出现在创建选择器并可用于创建员工", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page, "PUBLISHED");
  await page.route(
    "**/api/v1/knowledge-spaces?business_unit_id=bu_demo",
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
      item.url().endsWith("/api/v1/digital-employees/from-template"),
  );
  await page.route(
    "**/api/v1/digital-employees/from-template",
    async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "employee-from-managed-template",
          employee_key: "e2e_finance_review_employee",
          name: "E2E 财务审核员工",
          version: "1.0.0",
          scenario_type: template.scenario_type,
          domain: template.domain,
          template_code: template.code,
          workflow_key: template.workflow_key,
          business_unit_id: "bu_demo",
          service_identity: "digital_employee.e2e_finance_review_employee",
          status: "TRIAL",
          handoff_queue: template.handoff_queue,
          knowledge_policy: {},
          model_profile: {},
          tool_allowlist: template.tool_allowlist,
          manifest: {},
          activation_evaluation: {},
          activation_evaluated_at: null,
          config_revision: 1,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      });
    },
  );
  await page.goto("/employees/templates");
  const selector = page
    .locator(".section-card")
    .filter({ hasText: "选择一个岗位模板" })
    .first();
  await expect(selector.getByText("自定义已发布")).toBeVisible();
  await selector.getByRole("button", { name: "使用这个模板" }).click();
  const dialog = page.getByRole("dialog", {
    name: `创建 · ${templateName}`,
  });
  await dialog.locator(".ant-input").first().fill("E2E 财务审核员工");
  await dialog.getByRole("button", { name: "创建员工" }).click();
  expect((await requestPromise).postDataJSON()).toMatchObject({
    name: "E2E 财务审核员工",
    template_code: template.code,
    business_unit_id: "bu_demo",
  });
  await expect(
    page.getByText("试用员工已创建，请完成资源检查后评估激活"),
  ).toBeVisible();
});

test("编辑岗位模板草案生成新修订", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/edit`,
      ),
  );
  await page.route(
    `**/api/v1/digital-employee-templates/${templateId}/edit`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...template,
          name: "E2E 财务审核模板升级版",
          version: 2,
        }),
      });
    },
  );
  await page.goto("/employees/templates");
  await page.getByRole("button", { name: "编辑模板" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑岗位模板草案" });
  await dialog
    .locator(".ant-input")
    .first()
    .fill("E2E 财务审核模板升级版");
  await dialog.locator("textarea").nth(0).fill("更新后的岗位模板说明");
  await dialog.locator("textarea").nth(1).fill("退款审核\n财务复核");
  await dialog.locator("textarea").nth(2).fill("退款审核\n财务处理");
  await dialog.locator("textarea").nth(3).fill("refund-finance");
  await dialog
    .locator("textarea")
    .nth(4)
    .fill("ticket.read\nknowledge.search");
  await dialog.getByRole("button", { name: "保存新修订" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    name: "E2E 财务审核模板升级版",
    description: "更新后的岗位模板说明",
    capabilities: ["退款审核", "财务复核"],
    intents: ["退款审核", "财务处理"],
    skill_codes: ["refund-finance"],
    tool_allowlist: ["ticket.read", "knowledge.search"],
  });
  await expect(page.getByText("模板草案已更新并生成新修订")).toBeVisible();
});

test("已拒绝岗位模板可以重新打开", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockManagedTemplate(page, "REJECTED");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/digital-employee-templates/${templateId}/reopen`,
      ),
  );
  await page.goto("/employees/templates");
  await page.getByRole("button", { name: "重新打开模板" }).click();
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  await requestPromise;
});
