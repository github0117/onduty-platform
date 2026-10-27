import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();
const space = {
  id: "space-e2e",
  business_unit_id: "bu_demo",
  code: "e2e_knowledge",
  name: "E2E 售后知识",
  description: "知识库按钮验收",
  domain: "ecommerce",
  channel: "ecommerce_demo",
  category: "保温杯",
  category_profile_id: null,
  workflow_key: "customer_service_ticket_v1",
  owner_id: "e2e-agent",
  evaluation_required: false,
  status: "ACTIVE",
  document_count: 1,
  created_at: now,
  updated_at: now,
};

const document = {
  id: "document-e2e",
  space_id: space.id,
  business_unit_id: "bu_demo",
  title: "E2E 售后处理规范",
  doc_type: "SOP",
  owner_id: "e2e-agent",
  scope: {},
  source_type: null,
  source_ref: null,
  source_version: null,
  sync_status: null,
  last_synced_at: null,
  status: "ACTIVE",
  current_version_id: "version-e2e",
  created_at: now,
  updated_at: now,
};

const evaluationCase = {
  id: "case-e2e",
  business_unit_id: "bu_demo",
  knowledge_space_id: space.id,
  employee_id: null,
  name: "售后政策召回",
  query: "漏水如何退换",
  expected_titles: ["E2E 售后处理规范"],
  expect_no_grounding: false,
  scope: {},
  enabled: true,
  created_by: "e2e-agent",
  created_at: now,
  updated_at: now,
};

const evaluationRun = {
  id: "run-e2e",
  business_unit_id: "bu_demo",
  status: "SUCCEEDED",
  verdict: "PASS",
  top_k: 5,
  case_count: 1,
  passed_cases: 1,
  failed_cases: 0,
  recall_at_k: 1,
  mrr: 1,
  no_grounding_accuracy: 1,
  thresholds: {},
  results: [],
  error_message: null,
  created_by: "e2e-agent",
  created_at: now,
  started_at: now,
  completed_at: now,
};

function repairTask(status = "OPEN") {
  return {
    id: "repair-e2e",
    business_unit_id: "bu_demo",
    knowledge_space_id: space.id,
    evaluation_run_id: evaluationRun.id,
    evaluation_case_id: evaluationCase.id,
    status,
    priority: "P1",
    title: "售后政策未召回",
    query: "漏水如何退换",
    expected_titles: ["E2E 售后处理规范"],
    returned_titles: [],
    assignee_id: null,
    resolution_note: null,
    created_by: "e2e-agent",
    created_at: now,
    updated_at: now,
    resolved_at: null,
  };
}

async function mockKnowledgePage(
  page: Page,
  options: {
    cases?: unknown[];
    repairs?: unknown[];
    documents?: unknown[];
  } = {},
): Promise<void> {
  await page.route(
    "**/api/v1/knowledge-spaces?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([space]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge-documents?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(options.documents ?? [document]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(options.cases ?? [evaluationCase]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo",
    async (route) => {
      const items = options.repairs ?? [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length }),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-runs?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
}

async function openKnowledge(
  page: Page,
  path = "/knowledge/evaluation",
): Promise<void> {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto(path);
  await expect(
    page.getByRole("heading", { name: "知识库工作台", exact: true }),
  ).toBeVisible();
}

test("运行全部评测提交验收阈值并刷新结果", async ({ page }) => {
  await mockKnowledgePage(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge/evaluation-runs"),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-runs",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evaluationRun),
      });
    },
  );
  await openKnowledge(page, "/knowledge/evaluation");
  await page.getByRole("button", { name: "运行全部评测" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    top_k: 5,
    min_recall_at_k: 0.8,
    min_mrr: 0.6,
    min_no_grounding_accuracy: 0.8,
  });
  await expect(page.getByText("调参集评测通过：1/1")).toBeVisible();
});

test("评测案例可以停用并立即刷新状态", async ({ page }) => {
  await mockKnowledgePage(page);
  let enabled = true;
  await page.route(
    "**/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ ...evaluationCase, enabled }]),
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith(
        "/api/v1/knowledge/evaluation-cases/case-e2e",
      ),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-cases/case-e2e",
    async (route) => {
      enabled = false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...evaluationCase, enabled }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/evaluation");
  await page.getByRole("button", { name: "停用" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({ enabled: false });
  await expect(page.getByRole("button", { name: "启用" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "运行全部评测" }),
  ).toBeDisabled();
  await expect(page.getByText("暂无可运行的评测案例")).toBeVisible();
  await expect(
    page.getByText("当前案例均已停用。请启用至少一个案例后再运行全部评测。"),
  ).toBeVisible();
  await expect(page.getByText("评测案例状态已更新")).toBeVisible();
  const caseFilter = page.locator(".ant-select").filter({
    has: page.getByRole("combobox", { name: "评测案例范围" }),
  });
  await caseFilter.click();
  await page
    .locator('.ant-select-item-option[title="已停用"]')
    .click();
  await expect(page.getByRole("button", { name: "启用" })).toBeVisible();
});

test("评测状态过期时把后端拒绝映射为中文提示", async ({ page }) => {
  await mockKnowledgePage(page);
  await page.route(
    "**/api/v1/knowledge/evaluation-runs",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 409,
        contentType: "application/problem+json",
        body: JSON.stringify({
          type: "https://api.example.com/problems/evaluation-cases-empty",
          title: "No evaluation cases",
          status: 409,
          detail:
            "Create at least one enabled evaluation case before running.",
          code: "KNOWLEDGE_EVALUATION_CASES_EMPTY",
          correlation_id: "e2e-evaluation-empty",
          retryable: false,
          context: {},
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/evaluation");
  await page.getByRole("button", { name: "运行全部评测" }).click();
  await expect(
    page.getByText(
      "调参集还没有启用的评测案例，请先创建或启用。",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Create at least one enabled evaluation case before running.",
    ),
  ).toHaveCount(0);
});

test("评测数据集切换展示留出集冻结案例和分块指标", async ({ page }) => {
  const holdoutCase = {
    ...evaluationCase,
    id: "case-holdout-e2e",
    name: "留出集召回验收",
    query: "留出集漏水如何退换",
    dataset: "HOLDOUT",
    expected_titles: ["E2E 售后处理规范"],
    expected_chunk_ids: ["chunk-holdout-1"],
    expected_document_ids: ["doc-holdout-1"],
    negative_document_ids: ["doc-holdout-2"],
  };
  const holdoutRun = {
    ...evaluationRun,
    id: "run-holdout-e2e",
    dataset: "HOLDOUT",
    chunk_recall_at_k: 0.9,
    chunk_mrr: 0.8,
    document_recall_at_k: 0.95,
    document_mrr: 0.85,
    context_precision: 0.7,
    negative_violation_rate: 0,
    baseline: {
      dataset: "HOLDOUT",
      embedding_model: "local-hash",
      embedding_dimensions: 256,
      chunking_version: "v2",
      retrieval_mode: "hybrid",
      reranker: "local",
    },
  };
  await mockKnowledgePage(page);
  const holdoutCasesRequest = page.waitForRequest(
    (request) =>
      request.method() === "GET" &&
      request.url().includes("dataset=HOLDOUT") &&
      request.url().includes("/knowledge/evaluation-cases"),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo&dataset=HOLDOUT",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([holdoutCase]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-runs?business_unit_id=bu_demo&limit=10&dataset=HOLDOUT",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [holdoutRun], total: 1 }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/evaluation");
  await expect(page.getByText("调参集", { exact: true }).first()).toBeVisible();
  const datasetSelect = page.locator(".ant-select").filter({
    has: page.getByRole("combobox", { name: "评测数据集" }),
  });
  await datasetSelect.click();
  await page.locator('.ant-select-item-option[title="留出集"]').click();
  await holdoutCasesRequest;
  await expect(page.getByText("留出集召回验收")).toBeVisible();
  await expect(page.getByText("已冻结", { exact: true })).toBeVisible();
  await expect(page.getByText("禁止召回 1 份文档")).toBeVisible();
  await expect(page.getByText(/留出集评测：PASS/)).toBeVisible();
  await expect(page.getByText(/分块 Recall@K 0.900/)).toBeVisible();
  await expect(page.getByText(/embedding local-hash/)).toBeVisible();
  await expect(page.getByRole("button", { name: "停用" })).toHaveCount(0);
});

test("知识修复队列完成开始修复、回归验证和关闭任务", async ({
  page,
}) => {
  let status = "OPEN";
  await mockKnowledgePage(page, { repairs: [repairTask()] });
  await page.route(
    "**/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [repairTask(status)], total: 1 }),
      });
    },
  );
  const patch = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith("/api/v1/knowledge/repair-tasks/repair-e2e"),
  );
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e",
    async (route) => {
      const body = route.request().postDataJSON() as { status?: string };
      status = body.status ?? "IN_REPAIR";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(repairTask(status)),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e/verify",
    async (route) => {
      status = "VERIFIED";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(repairTask(status)),
      });
    },
  );
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "开始修复" }).click();
  expect((await patch).postDataJSON()).toEqual({
    status: "IN_REPAIR",
  });
  await expect(
    page.getByRole("button", { name: "一键验证修复" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "一键验证修复" }).click();
  await expect(page.getByRole("button", { name: "关闭任务" })).toBeVisible();
  await page.getByRole("button", { name: "关闭任务" }).click();
  await expect(page.getByText("修复任务状态已更新")).toBeVisible();
});

test("编辑知识文档提交标题、类型和所属空间", async ({ page }) => {
  await mockKnowledgePage(page);
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/versions",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith("/api/v1/knowledge-documents/document-e2e"),
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e",
    async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...document,
          title: "E2E 售后处理规范 2.0",
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/documents");
  await page.getByRole("button", { name: "E2E 售后处理规范" }).click();
  await page.getByRole("button", { name: /^编\s*辑$/ }).click();
  const dialog = page.getByRole("dialog", { name: "编辑知识文档" });
  await dialog.getByPlaceholder("文档标题").fill("E2E 售后处理规范 2.0");
  await dialog.getByRole("button").last().click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    title: "E2E 售后处理规范 2.0",
    doc_type: "SOP",
    space_id: "space-e2e",
  });
});

test("知识文档归档使用可见确认框并在成功后变为只读", async ({
  page,
}) => {
  await mockKnowledgePage(page);
  let archived = false;
  await page.route(
    "**/api/v1/knowledge-documents?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { ...document, status: archived ? "ARCHIVED" : "ACTIVE" },
        ]),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/versions",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/archive",
    async (route) => {
      archived = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...document, status: "ARCHIVED" }),
      });
    },
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/restore",
    async (route) => {
      archived = false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...document, status: "ACTIVE" }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/documents");
  await page.getByRole("button", { name: "E2E 售后处理规范" }).click();
  await page.getByRole("button", { name: /^归\s*档$/ }).click();
  const dialog = page.getByRole("dialog", { name: "归档知识文档？" });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText(/历史版本、引用与审计记录会保留/),
  ).toBeVisible();
  await dialog.getByRole("button", { name: /^归\s*档$/ }).click();
  await expect(page.getByText("知识文档已归档")).toBeVisible();
  await expect(page.getByText("该文档已归档")).toBeVisible();
  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", { name: "恢复使用" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "恢复使用" }).click();
  await expect(
    page.getByText("知识文档已恢复，可以继续检索和发布版本"),
  ).toBeVisible();
  await expect(page.getByText("该文档已归档")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "新建文本版本" }),
  ).toBeVisible();
});

test("上传知识文件前必须填写版本号并提交文件", async ({ page }) => {
  await mockKnowledgePage(page);
  let versionLabel = "";
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/versions",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  const uploadPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().includes(
        "/api/v1/knowledge-documents/document-e2e/uploads",
      ),
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/uploads*",
    async (route) => {
      versionLabel = new URL(route.request().url()).searchParams.get(
        "version_label",
      ) ?? "";
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          version_id: "upload-e2e",
          status: "PROCESSING",
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/documents");
  await page.getByRole("button", { name: "E2E 售后处理规范" }).click();
  const fileInput = page.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: "refund-policy.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 退款政策\n签收后七天内可申请退换。"),
  });
  await expect(page.getByText("请先填写版本号")).toBeVisible();
  await page.getByPlaceholder("上传版本号，例如 2.0").fill("2.1");
  await expect(
    page.getByPlaceholder("上传版本号，例如 2.0"),
  ).toHaveValue("2.1");
  await fileInput.setInputFiles({
    name: "refund-policy.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 退款政策\n签收后七天内可申请退换。"),
  });
  await uploadPromise;
  await expect.poll(() => versionLabel).toBe("2.1");
  await expect(
    page.getByText("文件已上传，正在异步解析和向量化"),
  ).toBeVisible();
});

test("没有评测案例时禁止运行全部评测", async ({ page }) => {
  await mockKnowledgePage(page, { cases: [] });
  await openKnowledge(page, "/knowledge/evaluation");
  await expect(
    page.getByRole("button", { name: "运行全部评测" }),
  ).toBeDisabled();
});

test("一键验证会处理停用的原评测案例", async ({ page }) => {
  await mockKnowledgePage(page, {
    cases: [{ ...evaluationCase, enabled: false }],
    repairs: [repairTask("IN_REPAIR")],
  });
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "一键验证修复" }).click();
  const dialog = page.getByRole("dialog", { name: "一键验证修复" });
  await expect(dialog.getByText("原失败问题")).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "开始自动验证" }),
  ).toBeEnabled();
});

test("留出集修复任务直接按留出集重新验证", async ({ page }) => {
  await mockKnowledgePage(page, { cases: [], repairs: [repairTask("IN_REPAIR")] });
  const holdoutCase = {
    ...evaluationCase,
    dataset: "HOLDOUT",
  };
  const holdoutCasesResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "GET" &&
      response.url().includes("/knowledge/evaluation-cases") &&
      response.url().includes("dataset=HOLDOUT"),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo&dataset=HOLDOUT",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([holdoutCase]),
      });
    },
  );
  const verifyPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge/repair-tasks/repair-e2e/verify"),
  );
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e/verify",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(repairTask("VERIFIED")),
      });
    },
  );
  await openKnowledge(page, "/knowledge/repairs");
  await holdoutCasesResponse;
  await page.getByRole("button", { name: "一键验证修复" }).click();
  await verifyPromise;
  await expect(
    page.getByRole("dialog", { name: "一键验证修复" }),
  ).toHaveCount(0);
  await expect(page.getByText("验证通过，可以关闭修复任务")).toBeVisible();
});

test("修复任务补充知识会跳到对应空间的文档并自动过滤", async ({
  page,
}) => {
  await mockKnowledgePage(page, {
    repairs: [repairTask("IN_REPAIR")],
    documents: [
      document,
      {
        ...document,
        id: "document-other-space",
        title: "其他空间文档",
        space_id: "space-other",
      },
    ],
  });
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "补充知识" }).click();
  await expect(page).toHaveURL(
    /\/knowledge\/documents\?space=space-e2e$/,
  );
  await expect(
    page.getByText("正在查看指定知识空间的文档"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "E2E 售后处理规范" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "其他空间文档" }),
  ).toHaveCount(0);
});

test("一键验证会自动建立回归案例、运行评测并更新任务", async ({
  page,
}) => {
  await mockKnowledgePage(page, {
    cases: [],
    repairs: [
      {
        ...repairTask("IN_REPAIR"),
        evaluation_case_id: null,
      },
    ],
  });
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge/evaluation-cases"),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-cases",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          ...evaluationCase,
          id: "case-from-repair",
          employee_id: null,
        }),
      });
    },
  );
  const runPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge/evaluation-runs"),
  );
  await page.route(
    "**/api/v1/knowledge/evaluation-runs",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(evaluationRun),
      });
    },
  );
  const updatePromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith("/api/v1/knowledge/repair-tasks/repair-e2e"),
  );
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e",
    async (route) => {
      if (route.request().method() !== "PATCH") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(repairTask("VERIFIED")),
      });
    },
  );
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "一键验证修复" }).click();
  const dialog = page.getByRole("dialog", { name: "一键验证修复" });
  await expect(dialog.getByText("漏水如何退换")).toBeVisible();
  await expect(
    dialog.getByText("E2E 售后处理规范"),
  ).toBeVisible();
  await dialog.getByRole("button", { name: "开始自动验证" }).click();
  const [create, run, update] = await Promise.all([
    requestPromise,
    runPromise,
    updatePromise,
  ]);
  expect(create.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    knowledge_space_id: space.id,
    query: "漏水如何退换",
    expected_titles: ["E2E 售后处理规范"],
  });
  expect(run.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    knowledge_space_id: space.id,
  });
  expect(update.postDataJSON()).toMatchObject({
    status: "VERIFIED",
  });
  await expect(
    page.getByText(
      "修复验证通过：1/1 个案例通过，可以关闭任务",
    ),
  ).toBeVisible();
});

test("回归评测状态过期时显示中文说明", async ({ page }) => {
  await mockKnowledgePage(page, {
    repairs: [repairTask("IN_REPAIR")],
  });
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e/verify",
    async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/problem+json",
        body: JSON.stringify({
          type: "https://api.example.com/problems/evaluation-cases-empty",
          title: "No evaluation cases",
          status: 409,
          detail:
            "Create at least one enabled evaluation case before running.",
          code: "KNOWLEDGE_EVALUATION_CASES_EMPTY",
          correlation_id: "e2e-repair-verify-empty",
          retryable: false,
          context: {},
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "一键验证修复" }).click();
  await expect(
    page.getByText(
      "暂时无法重新评测：请先在“质量评测”中启用至少一个评测案例。",
    ),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Create at least one enabled evaluation case before running.",
    ),
  ).toHaveCount(0);
});

test("回归验证未通过时显示中文状态而不是 IN_REPAIR", async ({ page }) => {
  await mockKnowledgePage(page, {
    repairs: [repairTask("IN_REPAIR")],
  });
  await page.route(
    "**/api/v1/knowledge/repair-tasks/repair-e2e/verify",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...repairTask("IN_REPAIR"),
          resolution_note: "回归评测未通过：仍有 2 个案例失败",
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/repairs");
  await page.getByRole("button", { name: "一键验证修复" }).click();
  await expect(
    page.getByText(
      "验证未通过，仍需继续修复。请修改或补充知识后再次验证。",
    ),
  ).toBeVisible();
  await expect(page.getByText("IN_REPAIR", { exact: true })).toHaveCount(0);
  await expect(page.getByText("修复中", { exact: true })).toBeVisible();
});

test("通用 FAQ CSV 批量导入会跳过无效行并发布有效知识", async ({
  page,
}) => {
  await mockKnowledgePage(page);
  const documentRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge-documents"),
  );
  await page.route(
    "**/api/v1/knowledge-documents",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          ...document,
          title: "FAQ · 售后工单多久内可以申请退款？",
        }),
      });
    },
  );
  const versionRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/knowledge-documents/document-e2e/versions",
      ),
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/versions",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "version-e2e",
          document_id: document.id,
          version_label: "import-v1",
          status: "DRAFT",
          content_hash: "e2e",
          effective_from: now,
          effective_to: null,
          embedding_model: "local",
          source_filename: null,
          source_mime_type: null,
          source_size_bytes: null,
          source_object_key: null,
          parser_name: null,
          parser_version: null,
          ingestion_error: null,
          processing_started_at: now,
          processed_at: now,
          chunk_count: 1,
          published_at: null,
          created_at: now,
        }),
      });
    },
  );
  const publishRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/knowledge-documents/document-e2e/versions/version-e2e/publish",
      ),
  );
  await page.route(
    "**/api/v1/knowledge-documents/document-e2e/versions/version-e2e/publish",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "version-e2e",
          document_id: document.id,
          version_label: "import-v1",
          status: "ACTIVE",
          content_hash: "e2e",
          effective_from: now,
          effective_to: null,
          embedding_model: "local",
          source_filename: null,
          source_mime_type: null,
          source_size_bytes: null,
          source_object_key: null,
          parser_name: null,
          parser_version: null,
          ingestion_error: null,
          processing_started_at: now,
          processed_at: now,
          chunk_count: 1,
          published_at: now,
          created_at: now,
        }),
      });
    },
  );
  await openKnowledge(page, "/knowledge/documents");
  await page.getByRole("button", { name: "批量导入 FAQ CSV" }).click();
  const dialog = page.getByRole("dialog", { name: "批量导入 FAQ 知识" });
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "faq.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      [
        "question,answer",
        "售后工单多久内可以申请退款？,签收后七天内可以申请退款。",
        "缺少答案的问题,",
      ].join("\n"),
    ),
  });
  await expect(dialog.getByText("可导入 1 条")).toBeVisible();
  await expect(dialog.getByText("需修正 1 条")).toBeVisible();
  await dialog.getByRole("button", { name: "导入并发布" }).click();
  const [create, version, publish] = await Promise.all([
    documentRequest,
    versionRequest,
    publishRequest,
  ]);
  expect(create.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    doc_type: "FAQ",
    space_id: space.id,
    title: "FAQ · 售后工单多久内可以申请退款？",
    scope: { source: "faq_csv", source_filename: "faq.csv" },
  });
  expect(version.postDataJSON()).toMatchObject({
    version_label: "import-v1",
  });
  expect(publish.postDataJSON()).toEqual({
    release_note: "Published from workbench",
  });
  await expect(
    page.getByText("FAQ 批量导入完成：已发布 1 条知识"),
  ).toBeVisible();
});
