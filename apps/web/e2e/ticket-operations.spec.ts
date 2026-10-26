import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const apiHeaders = {
  "X-Actor-Id": "e2e-ticket-ops",
  "X-Actor-Role": "admin",
  "X-Business-Unit-Id": "bu_demo",
};

async function realTicket(
  request: APIRequestContext,
): Promise<{
  item: Record<string, unknown>;
  detail: Record<string, unknown>;
}> {
  const list = await request.get(
    "/api/v1/tickets?business_unit_id=bu_demo&limit=50",
    { headers: apiHeaders },
  );
  expect(list.ok()).toBeTruthy();
  const item = (
    (await list.json()) as { items: Array<Record<string, unknown>> }
  ).items[0];
  expect(item).toBeTruthy();
  const response = await request.get(`/api/v1/tickets/${String(item.id)}`, {
    headers: apiHeaders,
  });
  expect(response.ok()).toBeTruthy();
  return {
    item,
    detail: (await response.json()) as Record<string, unknown>,
  };
}

function reviewTicket(
  item: Record<string, unknown>,
  detail: Record<string, unknown>,
  subject: string,
): Record<string, unknown> {
  return {
    ...item,
    subject,
  };
}

function detailWithDraft(
  detail: Record<string, unknown>,
  subject: string,
): Record<string, unknown> {
  return {
    ...detail,
    subject,
    workflow_state: "PENDING_REVIEW",
    status: "WAITING_REVIEW",
    draft: {
      id: "draft-e2e-operation",
      text: "您好，已核实订单信息，我们会按售后政策继续处理。",
      status: "PENDING_REVIEW",
      generator_provider: "e2e",
      generator_model: "contract-test",
      grounding_status: "GROUNDED",
      citations: [],
      claims: [],
      created_at: new Date().toISOString(),
      reviewed_at: null,
    },
  };
}

async function mockTicketDetail(
  page: Page,
  id: string,
  item: Record<string, unknown>,
  detail: Record<string, unknown>,
): Promise<void> {
  await page.route(
    "**/api/v1/tickets?business_unit_id=bu_demo&limit=50",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [item], total: 1 }),
      });
    },
  );
  await page.route(`**/api/v1/tickets/${id}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(detail),
    });
  });
}

async function openTicket(
  page: Page,
  id: string,
  subject: string,
): Promise<void> {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/tickets");
  await page.getByRole("button", { name: subject, exact: true }).click();
  await expect(page.getByRole("dialog", { name: subject })).toBeVisible();
}

test("演示工单示例按钮填充低风险和高风险内容并创建", async ({
  page,
}) => {
  await page.route(
    "**/api/v1/digital-employees?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: "employee-e2e",
            employee_key: "e2e_support",
            name: "E2E 客服员工",
          },
        ]),
      });
    },
  );
  await page.route(
    "**/api/v1/tickets?business_unit_id=bu_demo&limit=50",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  const createdDetail = {
    id: "ticket-created",
    subject: "账号被盗并发生数据泄露",
    version: 1,
    workflow_state: "NEEDS_HUMAN",
    status: "NEEDS_HUMAN",
    employee: { id: "employee-e2e", name: "E2E 客服员工", version: "1.0" },
    classification: null,
    priority: null,
    risk: { level: "R3", tags: ["数据泄露"] },
    routing: { queue_id: "SECURITY_REVIEW", human_reason: "HIGH_RISK" },
    sync: { status: "PENDING" },
    body: "我们发现账号被盗用，怀疑已经发生数据泄露，请立即处理。",
    summary: null,
    draft: null,
  };
  const createPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/tickets"),
  );
  await page.route("**/api/v1/tickets", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: "ticket-created" }),
    });
  });
  await page.route("**/api/v1/tickets/ticket-created", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(createdDetail),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/tickets");
  await page.getByRole("button", { name: "创建演示工单" }).click();
  const dialog = page.getByRole("dialog", { name: "创建演示工单" });
  await dialog.getByRole("button", { name: "填入低风险示例" }).click();
  await expect(dialog.getByPlaceholder("工单主题")).toHaveValue(
    "如何配置企业通知",
  );
  await dialog.getByRole("button", { name: "填入高风险示例" }).click();
  await expect(dialog.getByPlaceholder("工单主题")).toHaveValue(
    "账号被盗并发生数据泄露",
  );
  await dialog.getByRole("button", { name: "创建并处理" }).click();
  const request = await createPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    employee_id: "employee-e2e",
    subject: "账号被盗并发生数据泄露",
    body: "我们发现账号被盗用，怀疑已经发生数据泄露，请立即处理。",
  });
  await expect(page.getByText("工单已创建并完成数字员工处理")).toBeVisible();
});

test("工单草稿采用并完成提交当前版本", async ({ page, request }) => {
  const source = await realTicket(request);
  const id = String(source.item.id);
  const subject = `E2E 采用草稿 ${id.slice(0, 8)}`;
  const item = reviewTicket(source.item, source.detail, subject);
  const detail = detailWithDraft(source.detail, subject);
  await mockTicketDetail(page, id, item, detail);
  const reviewPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(`/api/v1/tickets/${id}/reviews`),
  );
  await page.route(`**/api/v1/tickets/${id}/reviews`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workflow_state: "SYNCING" }),
    });
  });
  await openTicket(page, id, subject);
  await page.getByRole("button", { name: "采用并完成" }).click();
  const review = await reviewPromise;
  expect(review.postDataJSON()).toMatchObject({
    expected_version: detail.version,
    decision: "ACCEPTED",
    reason_code: "AGENT_APPROVED",
  });
  await expect(
    page.getByRole("dialog", { name: subject }),
  ).toBeHidden();
});

test("保存修改并采用提交编辑后的回复正文", async ({ page, request }) => {
  const source = await realTicket(request);
  const id = String(source.item.id);
  const subject = `E2E 修改草稿 ${id.slice(0, 8)}`;
  const item = reviewTicket(source.item, source.detail, subject);
  const detail = detailWithDraft(source.detail, subject);
  await mockTicketDetail(page, id, item, detail);
  const reviewPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(`/api/v1/tickets/${id}/reviews`),
  );
  await page.route(`**/api/v1/tickets/${id}/reviews`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workflow_state: "SYNCING" }),
    });
  });
  await openTicket(page, id, subject);
  const edited =
    "您好，已核实订单和物流信息。我们将在 24 小时内按售后政策继续处理。";
  await page.locator(".ant-drawer-body textarea").last().fill(edited);
  await page.getByRole("button", { name: "保存修改并采用" }).click();
  const review = await reviewPromise;
  expect(review.postDataJSON()).toMatchObject({
    expected_version: detail.version,
    decision: "EDITED_AND_ACCEPTED",
    edited_text: edited,
  });
});

test("工单人工接管提交版本和接管原因", async ({ page, request }) => {
  const source = await realTicket(request);
  const id = String(source.item.id);
  const subject = `E2E 人工接管 ${id.slice(0, 8)}`;
  const item = reviewTicket(source.item, source.detail, subject);
  const detail = detailWithDraft(source.detail, subject);
  await mockTicketDetail(page, id, item, detail);
  const takeoverPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(`/api/v1/tickets/${id}/takeover`),
  );
  await page.route(`**/api/v1/tickets/${id}/takeover`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ workflow_state: "TAKEN_OVER" }),
    });
  });
  await openTicket(page, id, subject);
  await page.getByRole("button", { name: "人工接管", exact: true }).click();
  const takeover = await takeoverPromise;
  expect(takeover.postDataJSON()).toEqual({
    expected_version: detail.version,
    reason_code: "AGENT_REQUESTED",
    note: "从数字员工工作台接管",
  });
});

test("无草稿高风险工单只提供人工接管入口", async ({ page, request }) => {
  const source = await realTicket(request);
  const id = String(source.item.id);
  const subject = `E2E 高风险无草稿 ${id.slice(0, 8)}`;
  const item = {
    ...reviewTicket(source.item, source.detail, subject),
    risk_level: "R3",
  };
  const detail = {
    ...source.detail,
    subject,
    workflow_state: "NEEDS_HUMAN",
    status: "NEEDS_HUMAN",
    risk: { level: "R3", tags: ["数据泄露"] },
    draft: null,
  };
  await mockTicketDetail(page, id, item, detail);
  await openTicket(page, id, subject);
  await expect(page.getByText("该工单需要人工处理")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "人工接管" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "采用并完成" }),
  ).toHaveCount(0);
});

test("刷新队列按钮会重新请求工单列表", async ({ page }) => {
  let listCalls = 0;
  await page.route(
    "**/api/v1/tickets?business_unit_id=bu_demo&limit=50",
    async (route) => {
      listCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/tickets");
  await expect(page.getByText("暂无工单，请创建演示工单")).toBeVisible();
  const baseline = listCalls;
  await page.getByRole("button", { name: "刷新队列" }).click();
  await expect.poll(() => listCalls).toBeGreaterThan(baseline);
});

test("工单队列的分类和目标团队使用中文", async ({ page }) => {
  const item = {
    id: "ticket-display-e2e",
    subject: "保温杯材质咨询",
    status: "IN_PROGRESS",
    workflow_state: "PENDING_REVIEW",
    category_primary: "ecommerce_presales",
    priority: "P3",
    risk_level: "R0",
    queue_id: "ECOMMERCE_PRESALES",
    needs_human: false,
    version: 2,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  await mockTicketDetail(page, item.id, item, item);
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/tickets");
  await expect(
    page.getByText("电商售前咨询", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("电商售前", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("ecommerce_presales")).toHaveCount(0);
  await expect(page.getByText("ECOMMERCE_PRESALES")).toHaveCount(0);
});
