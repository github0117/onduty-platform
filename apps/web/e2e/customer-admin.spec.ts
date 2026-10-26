import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();

const approval = {
  id: "approval-e2e",
  business_unit_id: "bu_demo",
  employee_id: "employee-e2e",
  connector_id: "mcp-e2e",
  ticket_id: "ticket-e2e",
  conversation_id: "conversation-e2e",
  tool_id: "orders.refund",
  connector_code: "orders",
  tool_name: "orders.refund",
  arguments: { order_id: "ORDER-E2E-001", amount: 88 },
  required_role: "admin",
  policy: {},
  status: "PENDING",
  requested_by: "digital-employee",
  request_correlation_id: "correlation-e2e",
  reason: "买家符合退款条件，需执行一次退款写操作。",
  decided_by: null,
  decision_note: null,
  result: {},
  error_code: null,
  error_message: null,
  version: 3,
  decided_at: null,
  execution_started_at: null,
  completed_at: null,
  created_at: now,
  updated_at: now,
};

function incident(status = "OPEN") {
  return {
    id: "incident-e2e",
    business_unit_id: "bu_demo",
    approval_id: approval.id,
    employee_id: approval.employee_id,
    ticket_id: approval.ticket_id,
    conversation_id: approval.conversation_id,
    tool_id: approval.tool_id,
    failure_class: "TIMEOUT",
    status,
    error_code: "MCP_TIMEOUT",
    error_message: "订单系统响应超时，外部操作结果未知。",
    required_action: "先在订单中心核对退款是否发生，再填写事故结论。",
    assigned_to: null,
    resolution_note: null,
    resolution_outcome: null,
    reconciliation_status: "PENDING",
    reconciliation_tool_id: null,
    reconciliation_arguments: { order_id: "ORDER-E2E-001" },
    reconciliation_result: {},
    reconciliation_tool_call_id: null,
    reconciliation_attempts: 0,
    last_reconciled_at: null,
    compensation_tool_id: null,
    compensation_approval_id: null,
    compensation_status: "NOT_REQUESTED",
    compensation_result: {},
    version: 1,
    acknowledged_at: null,
    resolved_at: null,
    created_at: now,
    updated_at: now,
  };
}

async function openAdmin(page: Page, path: string): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "digital-workforce:test-identity",
      "platform-admin",
    );
    window.localStorage.setItem(
      "digital-workforce:test-business-unit",
      "bu_demo",
    );
  });
  await page.goto(path);
  const title = path.endsWith("/approvals")
    ? "待审批操作"
    : "执行异常";
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
}

test("管理员审批 MCP 写操作时提交版本和审批意见", async ({ page }) => {
  await page.route(
    "**/api/v1/mcp/tool-approvals?*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [approval], total: 1 }),
      });
    },
  );
  await page.route(
    "**/api/v1/mcp/action-incidents?*",
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
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/mcp/tool-approvals/approval-e2e/decisions",
      ),
  );
  await page.route(
    "**/api/v1/mcp/tool-approvals/approval-e2e/decisions",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...approval,
          status: "SUCCEEDED",
          decided_by: "e2e.admin",
          decision_note: "已核对订单和金额，同意退款。",
          version: 4,
        }),
      });
    },
  );
  await openAdmin(page, "/customer-service/approvals");
  await page.getByRole("button", { name: "审批并执行" }).click();
  const dialog = page.getByRole("dialog", {
    name: "审批并执行 MCP 写操作",
  });
  await expect(dialog.getByText("orders.refund")).toBeVisible();
  await dialog
    .getByPlaceholder("填写审批意见或拒绝理由")
    .fill("已核对订单和金额，同意退款。");
  await dialog.getByRole("button", { name: "确认审批并执行" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    decision: "APPROVE",
    expected_version: 3,
    note: "已核对订单和金额，同意退款。",
  });
  expect(request.headers()["x-actor-id"]).toBe("demo.admin");
  expect(request.headers()["x-actor-role"]).toBe("admin");
  await expect(
    page.getByText("审批通过，写工具已执行一次"),
  ).toBeVisible();
});

test("管理员先对账并关闭执行异常", async ({ page }) => {
  await page.route(
    "**/api/v1/mcp/tool-approvals?*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  let current = incident();
  await page.route(
    "**/api/v1/mcp/action-incidents?*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [current], total: 1 }),
      });
    },
  );
  const reconcilePromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/mcp/action-incidents/incident-e2e/reconcile",
      ),
  );
  await page.route(
    "**/api/v1/mcp/action-incidents/incident-e2e/reconcile",
    async (route) => {
      current = {
        ...current,
        version: 2,
        reconciliation_status: "SUCCEEDED",
        reconciliation_result: { text: "订单中心确认未发生退款" },
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current),
      });
    },
  );
  const resolvePromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/mcp/action-incidents/incident-e2e/resolve",
      ),
  );
  await page.route(
    "**/api/v1/mcp/action-incidents/incident-e2e/resolve",
    async (route) => {
      current = {
        ...current,
        status: "RESOLVED",
        resolution_note: "订单中心确认未发生退款，无需补偿。",
        resolution_outcome: "NOT_EXECUTED",
        version: 3,
      };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(current),
      });
    },
  );
  await openAdmin(page, "/customer-service/incidents");
  await page.getByRole("button", { name: "立即对账" }).click();
  const reconcile = await reconcilePromise;
  expect(reconcile.postDataJSON()).toMatchObject({
    expected_version: 1,
  });
  await expect(
    page.getByText("对账查询完成，请根据真实结果填写事故结论"),
  ).toBeVisible();
  await expect(
    page.getByText("对账结果：订单中心确认未发生退款"),
  ).toBeVisible();
  await page.getByRole("button", { name: "关闭事故" }).click();
  const dialog = page.getByRole("dialog", {
    name: "关闭执行异常",
  });
  await dialog.locator(".ant-select").click();
  await page
    .locator(".ant-select-dropdown:visible .ant-select-item-option")
    .first()
    .evaluate((element: HTMLElement) => element.click());
  await expect(
    dialog.locator(".ant-select-selection-item"),
  ).toHaveText("核对确认未执行");
  await dialog
    .getByPlaceholder(
      "必填：记录在哪个系统核对了什么结果，以及是否确认未执行或已执行",
    )
    .fill("订单中心确认未发生退款，无需补偿。");
  await dialog.getByRole("button", { name: "确认关闭" }).click();
  const resolve = await resolvePromise;
  expect(resolve.postDataJSON()).toEqual({
    expected_version: 2,
    note: "订单中心确认未发生退款，无需补偿。",
    outcome: "NOT_EXECUTED",
  });
  await expect(
    page.getByText("事故已关闭，处理结论已留档"),
  ).toBeVisible();
});
