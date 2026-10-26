import { expect, test, type Page } from "@playwright/test";

type WorkforceTask = {
  id: string;
  business_unit_id: string;
  title: string;
  objective: string;
  context: Record<string, unknown>;
  supervisor_employee_id: string | null;
  supervisor_employee_name: string | null;
  status: string;
  result_summary: string | null;
  created_by: string;
  steps: Array<Record<string, unknown>>;
  capability_gaps: Array<Record<string, unknown>>;
  employee_readiness: Array<Record<string, unknown>>;
  capability_assessed_at: string | null;
  created_at: string;
  updated_at: string;
};

const now = new Date().toISOString();

function makeTask(overrides: Partial<WorkforceTask> = {}): WorkforceTask {
  return {
    id: "task-e2e-supervisor",
    business_unit_id: "bu_demo",
    title: "售后退款联合处理",
    objective: "核实订单、物流与退款资格，并给出可审核处理建议。",
    context: {},
    supervisor_employee_id: "employee-supervisor",
    supervisor_employee_name: "客服智能主管",
    status: "PLAN_READY",
    result_summary: null,
    created_by: "e2e-agent",
    steps: [
      {
        id: "step-e2e-1",
        sequence: 1,
        title: "核实订单事实",
        instructions: "读取订单与物流信息，确认退款资格。",
        assigned_employee_id: "employee-after-sales",
        assigned_employee_key: "ecommerce_aftersales",
        assigned_employee_name: "售后专员",
        route_decision_id: null,
        required_capability: "售后核验",
        route_reason_code: "INTENT_MATCH",
        route_reason: "命中售后意图",
        route_confidence: 0.92,
        route_candidates: [],
        status: "PENDING",
        output: {},
        error_message: null,
        created_at: now,
        completed_at: null,
      },
    ],
    capability_gaps: [],
    employee_readiness: [],
    capability_assessed_at: now,
    created_at: now,
    updated_at: now,
    ...overrides,
  };
}

async function mockTaskList(
  page: Page,
  initial: WorkforceTask,
): Promise<{ current: () => WorkforceTask }> {
  let current = initial;
  await page.route(
    "**/api/v1/workforce/tasks?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [current], total: 1 }),
      });
    },
  );
  return { current: () => current };
}

async function openSupervisor(page: Page): Promise<void> {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/employees/supervisor");
  await expect(
    page.getByText("主管数字员工", { exact: true }).first(),
  ).toBeVisible();
}

test("主管生成任务分工并提交目标和上下文", async ({ page }) => {
  await page.route(
    "**/api/v1/workforce/tasks?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  const planned = makeTask({ title: "跨部门审批与资料补充" });
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/workforce/tasks"),
  );
  await page.route("**/api/v1/workforce/tasks", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(planned),
    });
  });
  await openSupervisor(page);

  await page.getByPlaceholder("例如：跨部门审批与资料补充").fill(
    "跨部门审批与资料补充",
  );
  await page
    .getByPlaceholder(
      "描述要解决的问题、需要哪些专业能力以及人工确认点。",
    )
    .fill("核对业务记录并补充申请资料，审批前必须人工确认。");
  await page.getByRole("button", { name: "生成任务分工" }).click();

  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    title: "跨部门审批与资料补充",
    objective: "核对业务记录并补充申请资料，审批前必须人工确认。",
  });
  await expect(
    page.getByText("主管数字员工已生成任务计划和员工分工"),
  ).toBeVisible();
});

test("主管重新检查能力与就绪度后刷新任务", async ({ page }) => {
  const { current } = await mockTaskList(page, makeTask());
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/workforce/tasks/task-e2e-supervisor/reassess",
      ),
  );
  await page.route(
    "**/api/v1/workforce/tasks/task-e2e-supervisor/reassess",
    async (route) => {
      const reassessed = makeTask({
        capability_assessed_at: new Date().toISOString(),
      });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(reassessed),
      });
    },
  );
  await openSupervisor(page);
  await page.getByRole("button", { name: "重新检查能力与就绪度" }).click();
  await requestPromise;
  expect(current().id).toBe("task-e2e-supervisor");
  await expect(
    page.getByText("能力检查已刷新，当前没有能力缺口"),
  ).toBeVisible();
});

test("主管执行任务分工并显示完成结果", async ({ page }) => {
  await mockTaskList(page, makeTask());
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/workforce/tasks/task-e2e-supervisor/execute",
      ),
  );
  await page.route(
    "**/api/v1/workforce/tasks/task-e2e-supervisor/execute",
    async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(
          makeTask({
            status: "EXECUTING",
            result_summary: "已进入执行队列",
          }),
        ),
      });
    },
  );
  await openSupervisor(page);
  await page.getByRole("button", { name: "执行任务分工" }).click();
  await requestPromise;
  await expect(
    page.getByText("主管任务已提交执行，专业员工正在处理"),
  ).toBeVisible();
});

test("主管能力缺口和阻塞员工会禁用执行按钮", async ({ page }) => {
  const blocked = makeTask({
    capability_gaps: [
      {
        step_id: null,
        sequence: null,
        step_title: "任务能力覆盖检查",
        required_capability: "财务处理能力",
        assigned_employee_name: "无可匹配员工",
        reason: "当前没有覆盖财务处理能力的员工。",
        recommended_template_code: null,
        recommended_template_name: "财务处理数字员工",
        recommended_domain: "finance",
        recommended_workflow_key: "customer_service_ticket_v1",
        recommended_capabilities: ["财务处理能力"],
        recommended_intents: ["退款"],
        recommended_skills: [],
        recommended_tools: [],
        status: "DRAFT_ONLY",
        approval_required: true,
      },
    ],
    employee_readiness: [
      {
        employee_id: "employee-after-sales",
        employee_key: "ecommerce_aftersales",
        employee_name: "售后专员",
        template_code: "ecommerce_aftersales",
        step_sequences: [1],
        status: "BLOCKED",
        checks: [
          {
            key: "status",
            label: "员工状态",
            status: "BLOCKED",
            detail: "员工已停用。",
          },
        ],
      },
    ],
  });
  await mockTaskList(page, blocked);
  await openSupervisor(page);
  await expect(
    page.getByRole("button", { name: "执行任务分工" }),
  ).toBeDisabled();
  await expect(
    page.getByText("存在阻塞执行的数字员工"),
  ).toBeVisible();
  await page.getByText("能力缺口与员工草案 · 1", { exact: true }).click();
  await expect(page.getByText("当前没有覆盖财务处理能力的员工。")).toBeVisible();
});

test("主管失败步骤重试后在冲突时显示持续失败提示", async ({ page }) => {
  const failed = makeTask({
    status: "FAILED",
    steps: [
      {
        ...makeTask().steps[0],
        status: "FAILED",
        error_message: "外部订单系统超时",
      },
    ],
  });
  await mockTaskList(page, failed);
  await page.route(
    "**/api/v1/workforce/tasks/task-e2e-supervisor/retry",
    async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/problem+json",
        body: JSON.stringify({
          type: "https://api.example.com/problems/task-conflict",
          title: "任务状态冲突",
          status: 409,
          detail: "任务已在其他窗口重新提交，请刷新后再试。",
          code: "WORKFORCE_TASK_CONFLICT",
          correlation_id: "e2e-workforce-conflict",
          retryable: true,
          context: {},
        }),
      });
    },
  );
  await openSupervisor(page);
  await page.getByRole("button", { name: "重试失败步骤" }).click();
  await expect(
    page.getByText("任务状态已经变化，请刷新后重新操作。"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "重试失败步骤" }),
  ).toBeEnabled();
});
