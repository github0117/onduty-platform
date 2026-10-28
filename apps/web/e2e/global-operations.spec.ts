import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();

async function mockOperations(page: Page): Promise<void> {
  await page.route(
    "**/api/v1/metrics/tools?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          calls: 8,
          succeeded: 7,
          failed: 1,
          denied: 0,
          success_rate: 0.875,
          failure_rate: 0.125,
          average_duration_ms: 120,
          p95_duration_ms: 320,
          by_tool: [
            {
              tool_key: "knowledge.search",
              calls: 8,
              succeeded: 7,
              failed: 1,
              denied: 0,
              success_rate: 0.875,
              average_duration_ms: 120,
              p95_duration_ms: 320,
            },
          ],
        }),
      });
    },
  );
  await page.route("**/api/v1/tool-calls?limit=80", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "call-e2e",
            employee_id: "employee-e2e",
            ticket_id: null,
            tool_key: "knowledge.search",
            action_type: "READ",
            risk_level: "R0",
            status: "SUCCEEDED",
            correlation_id: "corr-e2e",
            request_payload: {},
            response_summary: {},
            error_code: null,
            error_message: null,
            started_at: now,
            completed_at: now,
            duration_ms: 120,
          },
        ],
        total: 1,
      }),
    });
  });
  await page.route(
    "**/api/v1/agent-runs?business_unit_id=bu_demo&limit=50",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "run-e2e",
              business_unit_id: "bu_demo",
              employee_id: "employee-e2e",
              employee_name: "E2E 售后专员",
              employee_key: "e2e_after_sales",
              ticket_id: "ticket-e2e",
              ticket_subject: "E2E 退款处理",
              run_type: "ticket_agent",
              workflow_key: "customer_service_ticket_v1",
              status: "SUCCEEDED",
              correlation_id: "corr-run-e2e",
              input_summary: {},
              result_summary: {},
              error_code: null,
              error_message: null,
              started_at: now,
              completed_at: now,
              duration_ms: 520,
            },
          ],
          total: 1,
        }),
      });
    },
  );
  await page.route(
    "**/api/v1/agent-runs/run-e2e/trace",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          run: {
            id: "run-e2e",
            business_unit_id: "bu_demo",
            employee_id: "employee-e2e",
            employee_name: "E2E 售后专员",
            employee_key: "e2e_after_sales",
            ticket_id: "ticket-e2e",
            ticket_subject: "E2E 退款处理",
            run_type: "ticket_agent",
            workflow_key: "customer_service_ticket_v1",
            status: "SUCCEEDED",
            correlation_id: "corr-run-e2e",
            input_summary: {},
            result_summary: {},
            error_code: null,
            error_message: null,
            started_at: now,
            completed_at: now,
            duration_ms: 520,
          },
          events: [
            {
              id: "event-e2e",
              event_type: "tool",
              title: "检索售后知识",
              status: "SUCCEEDED",
              timestamp: now,
              duration_ms: 120,
              detail: { tool: "knowledge.search" },
            },
          ],
        }),
      });
    },
  );
  await page.route(
    "**/api/v1/metrics/sync?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          attempted: 4,
          pending: 0,
          syncing: 0,
          retrying: 0,
          succeeded: 4,
          failed: 0,
          terminal_count: 4,
          success_rate: 1,
          failure_rate: 0,
          average_attempts: 1,
          alerts: [],
        }),
      });
    },
  );
  await page.route(
    "**/api/v1/metrics/models?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          calls: 6,
          succeeded: 6,
          failed: 0,
          denied: 0,
          input_tokens: 1200,
          output_tokens: 300,
          total_tokens: 1500,
          estimated_cost: 0.01,
          budget_exceeded: 0,
          budget_forecast_alerts: 0,
          by_purpose: [
            {
              purpose: "ticket_reply",
              calls: 6,
              total_tokens: 1500,
              estimated_cost: 0.01,
            },
          ],
        }),
      });
    },
  );
  await page.route(
    "**/api/v1/metrics/rag?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          draft_count: 6,
          grounded_count: 5,
          no_knowledge_count: 1,
          citation_total: 8,
          average_citations: 1.33,
          grounding_rate: 0.83,
          claim_count: 12,
          cited_claim_count: 10,
          policy_claim_count: 4,
          policy_citation_coverage: 0.9,
          semantic_verified_claim_count: 9,
          citation_coverage: 0.9,
          unsupported_claim_count: 1,
          judge_provider: "local",
          judge_model: "rule",
          judge_calls: 2,
        }),
      });
    },
  );
}

test("根路径默认以平台管理员进入平台总览", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/");
  await expect(page).toHaveURL(/\/overview$/);
  await expect(
    page.getByRole("button", { name: "进入 60 秒主演示" }),
  ).toBeVisible();
});

test("平台总览的主演示入口进入企业服务台", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/overview");
  await page.getByRole("button", { name: "进入 60 秒主演示" }).click();
  await expect(page).toHaveURL(/\/customer-service$/);
  await expect(
    page.getByRole("heading", {
      name: "像员工一样问，自动分派给对的人",
    }),
  ).toBeVisible();
});

test("企业服务台 Agent 主演示可直接访问", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/customer-service?scenario=enterprise");
  await expect(
    page.getByRole("heading", {
      name: "像员工一样问，自动分派给对的人",
    }),
  ).toBeVisible();
  await expect(page).toHaveURL(
    /\/customer-service\?scenario=enterprise$/,
  );
});

test("运行与审计提交后台恢复任务并轮询完成状态", async ({ page }) => {
  let resetCalls = 0;
  let statusCalls = 0;
  let releaseReset: (() => void) | undefined;
  const resetGate = new Promise<void>((resolve) => {
    releaseReset = resolve;
  });
  await page.route("**/api/v1/demo/reset**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && pathname.endsWith("/demo/reset")) {
      resetCalls += 1;
      await resetGate;
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "reset-e2e",
          business_unit_id: "bu_demo",
          status: "QUEUED",
          message: "演示数据恢复任务已排队。",
        }),
      });
      return;
    }
    if (request.method() === "GET" && pathname.endsWith("/reset-e2e")) {
      statusCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          job_id: "reset-e2e",
          business_unit_id: "bu_demo",
          status: "SUCCEEDED",
          code: null,
          message: "演示数据已检查并恢复。",
          created_at: now,
          updated_at: now,
          finished_at: now,
        }),
      });
      return;
    }
    await route.continue();
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await page
    .getByRole("button", { name: "检查并恢复演示数据" })
    .click();
  const dialog = page.getByRole("dialog", { name: "检查并恢复演示数据？" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "开始恢复" }).click();
  await expect(
    dialog.getByRole("button", { name: "恢复中…" }),
  ).toBeDisabled();
  await expect.poll(() => resetCalls).toBe(1);
  releaseReset?.();
  await expect(
    page.locator(".action-feedback").getByText("演示数据已检查并恢复。"),
  ).toBeVisible();
  await expect(dialog).toBeHidden();
  expect(resetCalls).toBe(1);
  expect(statusCalls).toBeGreaterThan(0);
});

test("演示数据恢复失败时显示可执行中文提示", async ({ page }) => {
  await page.route("**/api/v1/demo/reset**", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({
        code: "DEMO_RESET_FAILED",
        title: "Demo reset failed",
        detail: "seed failed safely",
      }),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await page
    .getByRole("button", { name: "检查并恢复演示数据" })
    .click();
  const dialog = page.getByRole("dialog", { name: "检查并恢复演示数据？" });
  await dialog.getByRole("button", { name: "开始恢复" }).click();
  await expect(
    page.getByText("演示数据恢复失败，请检查后台服务后重试。"),
  ).toBeVisible();
  await expect(dialog).toBeVisible();
});

test("5 步引导可从第一步推进并进入对应页面", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await page.getByRole("button", { name: "5 步技术演示" }).click();
  const drawer = page.getByRole("dialog", {
    name: "企业服务台 Agent · 5 步技术演示",
  });
  await expect(drawer).toBeVisible();
  await expect(
    drawer.getByText("看清技术主线", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    drawer.getByText(/在员工名单中找到“研发支持数字员工”或“HR 入职资料数字员工”/),
  ).toBeVisible();
  await expect(
    drawer.getByText(
      /依次试“仓库文档”“入职材料”“账号被锁”/,
    ),
  ).toBeVisible();
  await drawer.getByRole("button", { name: "直接进入下一步" }).click();
  await expect(page).toHaveURL(/\/employees\/roster$/);
  await expect(
    page.getByRole("heading", { name: "数字员工名单", exact: true }),
  ).toBeVisible();
});

test("全局刷新数据按钮触发当前页面查询刷新", async ({ page }) => {
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
  await page.getByRole("button", { name: "刷新数据" }).click();
  await expect.poll(() => listCalls).toBeGreaterThan(baseline);
});

test("旧 page 查询参数会自动迁移到新路由", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/?page=tickets");
  await expect(page).toHaveURL(/\/tickets$/);
  await expect(
    page.getByRole("heading", { name: "内部工单与 HR 演示", exact: true }),
  ).toBeVisible();
});

test("运行与审计刷新按钮和 Agent Run Trace 抽屉可用", async ({ page }) => {
  await mockOperations(page);
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await expect(
    page.getByRole("heading", { name: "运行与审计" }),
  ).toBeVisible();
  await expect(page.getByText("8", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "刷新运行数据" }).click();
  await expect(
    page.getByRole("button", { name: "E2E 退款处理" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "E2E 退款处理" }).click();
  const drawer = page.getByRole("dialog", {
    name: "执行 Trace · E2E 退款处理",
  });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("检索售后知识")).toBeVisible();
  await expect(drawer.getByText("knowledge.search")).toBeVisible();
});

async function mockRagMetrics(
  page: Page,
  overrides: Record<string, unknown>,
): Promise<void> {
  await page.route(
    "**/api/v1/metrics/rag?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          draft_count: 6,
          grounded_count: 5,
          no_knowledge_count: 1,
          citation_total: 8,
          average_citations: 1.33,
          grounding_rate: 0.83,
          claim_count: 12,
          cited_claim_count: 10,
          policy_claim_count: 4,
          policy_citation_coverage: 0.9,
          semantic_verified_claim_count: 9,
          semantic_unsupported_claim_count: 0,
          provider_counts: {},
          embedding_model: "local-hash-256",
          embedding_quality: "demo",
          reindex_pending_versions: 0,
          stale_evaluation_chunk_refs: 0,
          ...overrides,
        }),
      });
    },
  );
}

test("运行与审计在演示嵌入模式下提示检索质量不代表语义水平", async ({
  page,
}) => {
  await mockOperations(page);
  await mockRagMetrics(page, { embedding_model: "local-hash-256" });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await expect(page.getByText(/检索模型 local-hash-256/)).toBeVisible();
  await expect(page.getByText(/本地哈希演示模式/)).toBeVisible();
});

test("运行与审计在语义嵌入模式下不显示演示提示", async ({ page }) => {
  await mockOperations(page);
  await mockRagMetrics(page, {
    embedding_model: "text-embedding-v3",
    embedding_quality: "semantic",
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/operations");
  await expect(page.getByText(/检索模型 text-embedding-v3/)).toBeVisible();
  await expect(page.getByText(/本地哈希演示模式/)).toHaveCount(0);
});
