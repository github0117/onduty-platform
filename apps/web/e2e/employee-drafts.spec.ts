import { expect, test, type Page } from "@playwright/test";

const draftId = "e2e-draft-review";
const draftName = "E2E 退款财务专员";

const draft = {
  id: draftId,
  business_unit_id: "bu_demo",
  source_task_id: null,
  source_step_id: null,
  required_capability: "退款财务审核",
  name: draftName,
  template_code: null,
  domain: "finance",
  workflow_key: "customer_service_ticket_v1",
  scenario_type: "customer_service_ticket",
  handoff_queue: "FINANCE_REVIEW",
  capabilities: ["退款审核", "金额核对"],
  intents: ["退款审核", "财务处理"],
  skill_codes: [],
  tool_allowlist: ["ticket.read", "knowledge.search"],
  status: "DRAFT",
  revision: 1,
  review_note: null,
  created_by: "e2e-admin",
  reviewed_by: null,
  reviewed_at: null,
  employee_id: null,
  evaluation: {},
  evaluated_at: null,
  published_at: null,
  rolled_back_at: null,
  promoted_template_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

async function mockDraftList(
  page: Page,
  status = "DRAFT",
  employeeId: string | null = null,
): Promise<void> {
  const currentDraft = {
    ...draft,
    status,
    employee_id: employeeId,
  };
  await page.route(
    "**/api/v1/digital-employee-drafts?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [currentDraft], total: 1 }),
      });
    },
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/revisions`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/review`,
    async (route) => {
      const body = route.request().postDataJSON() as {
        decision: "APPROVE" | "REJECT";
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...draft,
          status: body.decision === "APPROVE" ? "APPROVED" : "REJECTED",
          reviewed_by: "e2e-admin",
          reviewed_at: new Date().toISOString(),
        }),
      });
    },
  );
  for (const action of [
    "trial",
    "evaluate",
    "publish",
    "rollback",
  ]) {
    await page.route(
      `**/api/v1/digital-employee-drafts/${draftId}/${action}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(currentDraft),
        });
      },
    );
  }
}

test("员工草案批准按钮提交正确决定", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page);
  await page.goto("/employees/drafts");
  await expect(page.getByText(draftName, { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "批准草案" }).click();
  await page.getByPlaceholder("可填写批准意见").fill("E2E 批准");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/review`),
  );
  await page.getByRole("button", { name: "确认批准" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    decision: "APPROVE",
    note: "E2E 批准",
  });
});

test("员工草案拒绝按钮要求原因并提交拒绝", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page);
  await page.goto("/employees/drafts");
  await expect(page.getByText(draftName, { exact: true })).toBeVisible();

  await page
    .getByRole("button", { name: /^拒\s*绝$/ })
    .click();
  const rejectButton = page.getByRole("button", { name: "确认拒绝" });
  await expect(rejectButton).toBeDisabled();
  await page
    .getByPlaceholder("请填写拒绝原因，便于后续重新打开和修订")
    .fill("E2E 拒绝原因");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/review`),
  );
  await rejectButton.click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    decision: "REJECT",
    note: "E2E 拒绝原因",
  });
});

test("已批准草案可以创建试用员工", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page, "APPROVED");
  await page.goto("/employees/drafts");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/trial`),
  );
  await page.getByRole("button", { name: "创建试用员工" }).click();
  await requestPromise;
});

test("试用草案可以执行评测", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page, "TRIAL", "e2e-trial-employee");
  await page.goto("/employees/drafts");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/evaluate`),
  );
  await page.getByRole("button", { name: "执行评测" }).click();
  await requestPromise;
});

test("评测通过草案确认后可以发布", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(
    page,
    "EVALUATION_PASSED",
    "e2e-approved-employee",
  );
  await page.goto("/employees/drafts");
  await page
    .getByRole("button", { name: "发布为数字员工" })
    .click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/publish`),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  await requestPromise;
});

test("已发布草案确认后可以回滚停用", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(
    page,
    "PUBLISHED",
    "e2e-published-employee",
  );
  await page.goto("/employees/drafts");
  await page.getByRole("button", { name: "回滚停用" }).click();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(`/digital-employee-drafts/${draftId}/rollback`),
  );
  await page.getByRole("button", { name: /^确\s*认$/ }).click();
  await requestPromise;
});

test("编辑员工草案保存技能、意图和工具白名单", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/api/v1/digital-employee-drafts/${draftId}/edit`,
      ),
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/edit`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...draft,
          name: "E2E 退款财务专员升级版",
          revision: 2,
        }),
      });
    },
  );
  await page.goto("/employees/drafts");
  await page.getByRole("button", { name: "编辑草案" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑员工草案" });
  await dialog
    .locator(".ant-input")
    .first()
    .fill("E2E 退款财务专员升级版");
  await dialog
    .locator("textarea")
    .nth(0)
    .fill("退款审核\n金额核对\n财务复核");
  await dialog
    .locator("textarea")
    .nth(1)
    .fill("退款审核\n财务处理");
  await dialog
    .locator("textarea")
    .nth(2)
    .fill("refund-finance");
  await dialog
    .locator("textarea")
    .nth(3)
    .fill("ticket.read\nknowledge.search\norders.read");
  await dialog.getByRole("button", { name: "保存草案" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    name: "E2E 退款财务专员升级版",
    capabilities: ["退款审核", "金额核对", "财务复核"],
    intents: ["退款审核", "财务处理"],
    skill_codes: ["refund-finance"],
    tool_allowlist: ["ticket.read", "knowledge.search", "orders.read"],
  });
  await expect(page.getByText("员工草案已更新")).toBeVisible();
});

test("员工草案可以对比差异并回退旧版本", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(page);
  const currentDraft = {
    ...draft,
    name: "E2E 退款财务专员升级版",
    capabilities: ["退款审核", "金额核对", "财务复核"],
    revision: 2,
  };
  const previousSnapshot = {
    ...draft,
    capabilities: ["退款审核"],
    intents: ["退款审核"],
    tool_allowlist: ["ticket.read"],
    revision: 1,
  };
  await page.route(
    "**/api/v1/digital-employee-drafts?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [currentDraft],
          total: 1,
        }),
      });
    },
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/revisions`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "e2e-revision-1",
            draft_id: draftId,
            revision: 1,
            status: "DRAFT",
            snapshot: previousSnapshot,
            change_note: "Employee draft created",
            created_by: "e2e-admin",
            created_at: new Date().toISOString(),
          },
        ]),
      });
    },
  );
  const restoreRequest = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/api/v1/digital-employee-drafts/${draftId}/revisions/1/restore`,
      ),
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/revisions/1/restore`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...currentDraft,
          ...previousSnapshot,
          revision: 3,
        }),
      });
    },
  );
  await page.goto("/employees/drafts");
  await page.getByText("版本历史 · 1").click();
  await page
    .getByRole("button", { name: /对比版本/ })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "版本对比 · v1 → 当前 v2",
  });
  await expect(
    dialog.getByText("E2E 退款财务专员", { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByText("E2E 退款财务专员升级版"),
  ).toBeVisible();
  await expect(
    dialog.getByText("退款审核、金额核对、财务复核"),
  ).toBeVisible();
  await dialog
    .getByRole("button", { name: "回退到此版本" })
    .click();
  await restoreRequest;
  await expect(page.getByText("已回退到 v1")).toBeVisible();
});

test("已发布草案可以沉淀为岗位模板", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await mockDraftList(
    page,
    "PUBLISHED",
    "e2e-published-employee",
  );
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/api/v1/digital-employee-drafts/${draftId}/promote-template`,
      ),
  );
  await page.route(
    `**/api/v1/digital-employee-drafts/${draftId}/promote-template`,
    async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "template-from-draft",
          code: "refund_finance_e2e",
          name: "退款财务专员模板",
          description: "来自 E2E 草案",
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
          source_draft_id: draftId,
          version: 1,
          published_at: null,
          knowledge_bindings: [],
          mcp_bindings: [],
          model_profile: {},
          knowledge_policy: {},
          readiness_snapshot: {},
        }),
      });
    },
  );
  await page.goto("/employees/drafts");
  await page.getByRole("button", { name: "沉淀为岗位模板" }).click();
  await requestPromise;
  await expect(
    page.getByText("已生成模板草案，请到岗位模板页面完成批准和发布"),
  ).toBeVisible();
});
