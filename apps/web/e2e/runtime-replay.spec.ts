import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import { useIdentity } from "./helpers/identity";

const apiHeaders = {
  "X-Actor-Id": "e2e-agent",
  "X-Actor-Role": "admin",
  "X-Business-Unit-Id": "bu_demo",
};
const createdTicketIds = new Set<string>();
const createdConversationIds = new Set<string>();

async function createProductConversation(
  request: APIRequestContext,
  content = "这款保温杯是什么材质，能保温多久？",
): Promise<{ conversationId: string; requesterRef: string; ticketId: string }> {
  const suffix = Date.now().toString(36);
  const employees = await request.get(
    "/api/v1/digital-employees?business_unit_id=bu_demo",
    { headers: apiHeaders },
  );
  expect(employees.ok()).toBeTruthy();
  const employee = (
    (await employees.json()) as Array<{ id: string; employee_key: string }>
  ).find((item) => item.employee_key === "demo_vacuum_cup_customer_service");
  expect(employee).toBeTruthy();

  const products = await request.get(
    "/api/v1/ecommerce/products?business_unit_id=bu_demo",
    { headers: apiHeaders },
  );
  expect(products.ok()).toBeTruthy();
  const product = (
    (await products.json()) as Array<{ id: string; name: string; sku: string }>
  )[0];
  expect(product).toBeTruthy();

  const categories = await request.get(
    "/api/v1/ecommerce/categories?business_unit_id=bu_demo",
    { headers: apiHeaders },
  );
  expect(categories.ok()).toBeTruthy();
  const category = (
    (await categories.json()) as Array<{ id: string; code: string; name: string }>
  ).find((item) => item.code === "vacuum_cup");

  const requesterRef = `e2e-runtime-replay-${suffix}`;
  const conversation = await request.post(
    "/api/v1/customer-service/conversations",
    {
      headers: apiHeaders,
      data: {
        business_unit_id: "bu_demo",
        employee_id: employee!.id,
        requester_ref: requesterRef,
        category_name: category?.name,
        category_profile_id: category?.id,
      },
    },
  );
  expect(conversation.ok()).toBeTruthy();
  const conversationId = ((await conversation.json()) as { id: string }).id;
  createdConversationIds.add(conversationId);

  const message = await request.post(
    `/api/v1/customer-service/conversations/${conversationId}/messages`,
    {
      headers: apiHeaders,
      data: { content, product_id: product.id, sku: product.sku },
    },
  );
  expect(message.ok()).toBeTruthy();
  const ticketId = (
    (await message.json()) as { current_ticket_id: string }
  ).current_ticket_id;
  expect(ticketId).toBeTruthy();
  createdTicketIds.add(ticketId);
  return { conversationId, requesterRef, ticketId };
}

async function waitForTerminalTurn(
  request: APIRequestContext,
  conversationId: string,
): Promise<string> {
  let turnId = "";
  await expect
    .poll(
      async () => {
        const detail = await request.get(
          `/api/v1/customer-service/conversations/${conversationId}`,
          { headers: apiHeaders },
        );
        const payload = (await detail.json()) as {
          current_turn?: { id?: string; status?: string };
        };
        turnId = payload.current_turn?.id ?? "";
        return payload.current_turn?.status;
      },
      // The live stack answers with the configured model; a busy provider or
      // the local fallback can take tens of seconds per turn.
      { timeout: 60_000 },
    )
    .toBe("COMPLETED");
  expect(turnId).toBeTruthy();
  return turnId;
}

async function openWorkbenchConversation(
  page: Page,
  requesterRef: string,
): Promise<void> {
  await page.goto("/customer-service/workbench");
  await page.getByText("全部", { exact: true }).click();
  await page
    .getByRole("button", { name: new RegExp(requesterRef) })
    .click();
}

async function openReplayDrawer(page: Page): Promise<void> {
  await page.getByRole("button", { name: "运行回放" }).click();
  await expect(page.getByText(/运行回放 · 会话/)).toBeVisible();
}

test.afterEach(async ({ request }) => {
  for (const conversationId of createdConversationIds) {
    const response = await request.post(
      `/api/v1/customer-service/conversations/${conversationId}/archive-test-data`,
      { headers: apiHeaders },
    );
    expect([200, 404]).toContain(response.status());
  }
  for (const ticketId of createdTicketIds) {
    const response = await request.post(
      `/api/v1/tickets/${ticketId}/archive-test-data`,
      { headers: apiHeaders },
    );
    expect([200, 404]).toContain(response.status());
  }
  createdConversationIds.clear();
  createdTicketIds.clear();
});

test("工作台运行回放展示轮次、事件时间线和上下文快照", async ({
  page,
  request,
}) => {
  const { conversationId, requesterRef } =
    await createProductConversation(request);
  const turnId = await waitForTerminalTurn(request, conversationId);

  await useIdentity(page, "service-agent");
  await openWorkbenchConversation(page, requesterRef);
  await openReplayDrawer(page);

  await expect(page.getByText("#1", { exact: true })).toBeVisible();
  await expect(page.getByText(/共 \d+ 个事件，已加载 \d+ 个/)).toBeVisible();
  await expect(page.getByText("入队", { exact: true })).toBeVisible();
  await expect(page.getByText("组装上下文", { exact: true })).toBeVisible();
  await expect(
    page.getByText("发送门禁评估", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("本轮上下文快照")).toBeVisible();
  await expect(page.getByText("Skill 契约快照")).toBeVisible();
  await expect(page.getByText("完成", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("交接记录", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无交接", { exact: false })).toBeVisible();

  // 详情 API 与抽屉展示一致：当前轮次已完成并记录了上下文快照。
  const detail = await request.get(
    `/api/v1/customer-service/conversations/${conversationId}/turns/${turnId}`,
    { headers: apiHeaders },
  );
  expect(detail.ok()).toBeTruthy();
  const payload = (await detail.json()) as {
    status: string;
    context: Record<string, unknown> | null;
  };
  expect(payload.status).toBe("COMPLETED");
  expect(payload.context).toBeTruthy();

  // 关闭后重新打开走同一入口，不依赖手工刷新。
  await page.getByRole("button", { name: "关闭" }).click();
  await openReplayDrawer(page);
  await expect(page.getByText("#1", { exact: true })).toBeVisible();
});

test("事件分页按钮在仍有更多事件时可继续加载", async ({
  page,
  request,
}) => {
  const { conversationId, requesterRef } =
    await createProductConversation(request);
  await waitForTerminalTurn(request, conversationId);

  const event = (sequence: number) => ({
    id: `e2e-event-${sequence}`,
    turn_id: "e2e-turn",
    conversation_id: conversationId,
    sequence,
    event_type: "TURN_STARTED",
    status: "RUNNING",
    stage_label: "处理中",
    actor_type: "WORKER",
    actor_id: "e2e-worker",
    correlation_id: null,
    payload: {},
    created_at: new Date().toISOString(),
  });
  let pages = 0;
  await page.route(
    "**/api/v1/customer-service/conversations/*/turns/*/events*",
    async (route) => {
      pages += 1;
      const url = new URL(route.request().url());
      const afterSequence = url.searchParams.get("after_sequence");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          afterSequence
            ? {
                events: [event(3)],
                total: 3,
                has_more: false,
              }
            : {
                events: [event(1), event(2)],
                total: 3,
                has_more: true,
              },
        ),
      });
    },
  );

  await useIdentity(page, "service-agent");
  await openWorkbenchConversation(page, requesterRef);
  await openReplayDrawer(page);

  await expect(
    page.getByText("共 3 个事件，已加载 2 个"),
  ).toBeVisible();
  const loadMore = page.getByRole("button", { name: "加载更多事件" });
  await expect(loadMore).toBeVisible();
  await loadMore.click();
  await expect(
    page.getByText("共 3 个事件，已加载 3 个"),
  ).toBeVisible();
  await expect(loadMore).toHaveCount(0);
  expect(pages).toBeGreaterThanOrEqual(2);
});

test("人工接管与交还记录在运行回放中可读", async ({ page, request }) => {
  const { conversationId, requesterRef, ticketId } =
    await createProductConversation(request);
  await waitForTerminalTurn(request, conversationId);

  const current = await request.get(
    `/api/v1/customer-service/conversations/${conversationId}`,
    { headers: apiHeaders },
  );
  expect(current.ok()).toBeTruthy();
  const version = ((await current.json()) as { version: number }).version;
  const takeover = await request.post(
    `/api/v1/customer-service/conversations/${conversationId}/takeover`,
    {
      headers: apiHeaders,
      data: { expected_version: version },
    },
  );
  expect(takeover.ok()).toBeTruthy();
  expect(
    ((await takeover.json()) as { assigned_agent_id: string | null })
      .assigned_agent_id,
  ).toBe("e2e-agent");
  // 已完成的工单不会被接管重开，人工先等待买家提出新问题。
  const completedTicket = await request.get(`/api/v1/tickets/${ticketId}`, {
    headers: apiHeaders,
  });
  expect(completedTicket.ok()).toBeTruthy();
  expect(
    ((await completedTicket.json()) as { workflow_state: string })
      .workflow_state,
  ).toBe("COMPLETED");

  const before = await request.get(
    `/api/v1/customer-service/conversations/${conversationId}`,
    { headers: apiHeaders },
  );
  const beforeMessages = (
    (await before.json()) as { messages: Array<{ role: string }> }
  ).messages;
  const buyerMessage = await request.post(
    `/api/v1/customer-service/conversations/${conversationId}/messages`,
    {
      headers: apiHeaders,
      data: { content: "你好，我还有个问题。" },
    },
  );
  expect(buyerMessage.ok()).toBeTruthy();
  const humanOwned = await request.get(
    `/api/v1/customer-service/conversations/${conversationId}`,
    { headers: apiHeaders },
  );
  expect(humanOwned.ok()).toBeTruthy();
  const humanOwnedConversation = (await humanOwned.json()) as {
    current_ticket_id: string;
    current_turn: { status: string } | null;
    messages: Array<{ role: string }>;
  };
  expect(humanOwnedConversation.current_turn?.status).toBe("NEEDS_HUMAN");
  expect(humanOwnedConversation.messages.length).toBe(
    beforeMessages.length + 1,
  );
  expect(humanOwnedConversation.current_ticket_id).toBe(ticketId);
  const reopenedTicket = await request.get(`/api/v1/tickets/${ticketId}`, {
    headers: apiHeaders,
  });
  expect(reopenedTicket.ok()).toBeTruthy();
  const reopened = (await reopenedTicket.json()) as {
    workflow_state: string;
    needs_human: boolean;
  };
  expect(reopened.workflow_state).toBe("NEEDS_HUMAN");
  expect(reopened.needs_human).toBe(true);

  const reply = await request.post(
    `/api/v1/customer-service/conversations/${conversationId}/manual-replies`,
    {
      headers: apiHeaders,
      data: {
        content: "已为您核实，保温杯内胆为 316 不锈钢。",
        resolve: true,
      },
    },
  );
  expect(reply.ok()).toBeTruthy();
  expect(
    ((await reply.json()) as { assigned_agent_id: string | null })
      .assigned_agent_id,
  ).toBeNull();

  await useIdentity(page, "service-agent");
  await openWorkbenchConversation(page, requesterRef);
  await openReplayDrawer(page);

  await expect(page.getByText("人工接管", { exact: true })).toBeVisible();
  await expect(page.getByText("人工交还", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/数字员工 → 人工|→ 人工$/),
  ).toBeVisible();
  await expect(page.getByText(/人工 → /)).toBeVisible();
  await expect(
    page.getByText("人工最后回复：已为您核实，保温杯内胆为 316 不锈钢。"),
  ).toBeVisible();
});

test("运营页展示运行时健康与运行队列，且非管理员看不到运行时卡片", async ({
  page,
  request,
}) => {
  const { requesterRef } = await createProductConversation(request);

  await useIdentity(page, "platform-admin");
  await page.goto("/operations");

  const health = page.getByText("会话运行时健康", { exact: true });
  await expect(health).toBeVisible();
  await expect(page.getByText("轮次总数", { exact: true })).toBeVisible();
  await expect(page.getByText("自动发送率", { exact: true })).toBeVisible();
  await expect(page.getByText("交接率", { exact: true })).toBeVisible();
  await expect(page.getByText("卡住轮次", { exact: true })).toBeVisible();
  await expect(page.getByText("知识缺口 Top 5", { exact: true })).toBeVisible();

  const queue = page.getByText("运行队列", { exact: true });
  await expect(queue).toBeVisible();
  const row = page
    .locator("tr", { hasText: requesterRef })
    .first();
  await expect(row).toBeVisible();
  await expect(row.getByText("已完成", { exact: true })).toBeVisible();

  // 状态筛选切换后列表自动刷新。
  const queueCard = page
    .locator(".section-card", { hasText: "运行队列" })
    .first();
  await queueCard.locator(".ant-select").click();
  await page.locator('.ant-select-item-option[title="已完成"]').click();
  await expect(
    page.locator("tr", { hasText: requesterRef }).first(),
  ).toBeVisible();
  await queueCard.locator(".ant-select").click();
  await page.locator('.ant-select-item-option[title="全部状态"]').click();

  // 非管理员（业务经理）可进入运营页，但看不到运行时健康与运行队列。
  await useIdentity(page, "business-manager");
  await page.goto("/operations");
  await expect(page.getByText("业务价值", { exact: false }).first()).toBeVisible();
  await expect(
    page.getByText("会话运行时健康", { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("运行队列", { exact: true })).toHaveCount(0);
});
