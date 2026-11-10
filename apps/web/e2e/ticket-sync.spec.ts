import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const apiHeaders = {
  "X-Actor-Id": "e2e-ticket",
  "X-Actor-Role": "admin",
  "X-Business-Unit-Id": "bu_demo",
};

async function failedSyncTicket(
  request: APIRequestContext,
): Promise<{
  item: Record<string, unknown>;
  subject: string;
  detail: Record<string, unknown>;
}> {
  const list = await request.get(
    "/api/v1/tickets?business_unit_id=bu_demo&limit=50",
    { headers: apiHeaders },
  );
  expect(list.ok()).toBeTruthy();
  const item = (
    (await list.json()) as {
      items: Array<{ id: string; subject: string }>;
    }
  ).items[0];
  expect(item).toBeTruthy();
  const subject = `E2E 同步失败工单 ${item.id.slice(0, 8)}`;
  const detailResponse = await request.get(
    `/api/v1/tickets/${item.id}`,
    { headers: apiHeaders },
  );
  expect(detailResponse.ok()).toBeTruthy();
  const detail = (await detailResponse.json()) as Record<string, unknown>;
  detail.subject = subject;
  detail.workflow_state = "PENDING_REVIEW";
  detail.status = "WAITING_REVIEW";
  detail.sync = {
    status: "FAILED",
    attempts: 1,
    error: "e2e sync failure",
    external_request_id: null,
    synced_at: null,
  };
  detail.draft = {
    id: "e2e-sync-draft",
    text: "E2E 同步重试草稿",
    status: "PENDING_REVIEW",
    generator_provider: "e2e",
    generator_model: "mock",
    grounding_status: "GROUNDED",
    citations: [],
    claims: [],
    created_at: new Date().toISOString(),
    reviewed_at: null,
  };
  return {
    item: { ...item, subject },
    subject,
    detail,
  };
}

async function openFailedTicket(
  page: Page,
  item: Record<string, unknown>,
  subject: string,
  detail: Record<string, unknown>,
): Promise<void> {
  const id = String(item.id);
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
  await page.route(
    `**/api/v1/tickets/${id}`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(detail),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/tickets");
  await page.getByRole("button", { name: subject, exact: true }).click();
}

test("工单详情内嵌只读工作流进度", async ({ page, request }) => {
  const ticket = await failedSyncTicket(request);
  const id = String(ticket.item.id);
  const now = new Date().toISOString();
  await page.route(`**/api/v1/tickets/${id}/workflow-runs`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "e2e-workflow-run",
            business_unit_id: "bu_demo",
            workflow_type: "ticket_sync",
            aggregate_type: "ticket",
            aggregate_id: id,
            status: "SUCCEEDED",
            current_step: null,
            context: {},
            created_at: now,
            updated_at: now,
            steps: [
              {
                id: "e2e-workflow-step",
                name: "sync_external",
                status: "SUCCEEDED",
                attempt_count: 1,
                max_attempts: 5,
                available_at: now,
                started_at: now,
                finished_at: now,
                last_error: null,
                output: null,
              },
            ],
          },
        ],
        limit: 20,
        offset: 0,
      }),
    });
  });
  await openFailedTicket(page, ticket.item, ticket.subject, ticket.detail);

  const card = page
    .locator(".ant-card")
    .filter({ hasText: "工作流进度" })
    .first();
  await expect(card).toBeVisible();
  // 状态枚举由后端以大写返回，必须映射为中文而不是回退成原始值。
  await expect(card.getByText("已完成", { exact: true })).toBeVisible();
  await expect(card.getByText("成功", { exact: true })).toBeVisible();
  await expect(card.getByText("工单外部同步", { exact: true })).toBeVisible();
  // 步骤名带序号前缀，需精确匹配，避免与运行类型里的「外部同步」混淆。
  await expect(card.getByText(/^1\. 外部同步$/)).toBeVisible();
  await expect(card.getByText("尝试 1/5")).toBeVisible();
  await expect(card.getByRole("button", { name: /重放/ })).toHaveCount(0);
});

test("失败工单可以重试外部同步", async ({ page, request }) => {
  const ticket = await failedSyncTicket(request);
  await openFailedTicket(
    page,
    ticket.item,
    ticket.subject,
    ticket.detail,
  );
  const retryPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/tickets/${String(ticket.item.id)}/sync-attempts`,
      ),
  );
  await page.route(
    `**/api/v1/tickets/${String(ticket.item.id)}/sync-attempts`,
    async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ status: "PENDING" }),
      });
    },
  );
  await page.getByRole("button", { name: "重试外部同步" }).click();
  const retry = await retryPromise;
  expect(retry.postDataJSON()).toMatchObject({
    expected_version: ticket.detail.version,
    reason_code: "MANUAL_SYNC_RETRY",
  });
});
