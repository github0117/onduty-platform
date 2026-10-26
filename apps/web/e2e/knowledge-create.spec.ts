import { expect, test, type Page } from "@playwright/test";

const spaceId = "e2e-create-space";
const documentId = "e2e-create-document";

const space = {
  id: spaceId,
  business_unit_id: "bu_demo",
  code: "e2e_space",
  name: "E2E 知识空间",
  description: "E2E",
  domain: "ecommerce",
  channel: "ecommerce_demo",
  category: "保温杯",
  category_profile_id: null,
  workflow_key: "customer_service_ticket_v1",
  owner_id: "e2e-admin",
  evaluation_required: false,
  status: "ACTIVE",
  document_count: 0,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const document = {
  id: documentId,
  space_id: spaceId,
  business_unit_id: "bu_demo",
  title: "E2E 文档",
  doc_type: "SOP",
  owner_id: "e2e-admin",
  scope: {},
  source_type: null,
  source_ref: null,
  source_version: null,
  sync_status: null,
  last_synced_at: null,
  status: "ACTIVE",
  current_version_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

async function mockKnowledgeBase(page: Page): Promise<void> {
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
        body: JSON.stringify([document]),
      });
    },
  );
  await page.route(
    `**/api/v1/knowledge-documents/${documentId}/versions`,
    async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "e2e-version",
            document_id: documentId,
            version_label: "2.0",
            status: "PROCESSING",
            content_hash: "e2e",
            effective_from: new Date().toISOString(),
            effective_to: null,
            embedding_model: "local",
            source_filename: null,
            source_mime_type: null,
            source_size_bytes: null,
            source_object_key: null,
            parser_name: null,
            parser_version: null,
            ingestion_error: null,
            processing_started_at: new Date().toISOString(),
            processed_at: null,
            chunk_count: 0,
            published_at: null,
            created_at: new Date().toISOString(),
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
}

test("新建知识空间按钮提交空间配置", async ({ page }) => {
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/knowledge-spaces"),
  );
  await page.route("**/api/v1/knowledge-spaces", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify(space),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/spaces");
  await page.getByRole("button", { name: "新建知识空间" }).click();
  const dialog = page.getByRole("dialog", { name: "新建知识空间" });
  await dialog
    .getByPlaceholder("空间编码，例如 refund_policy")
    .fill("e2e_space");
  await dialog
    .getByPlaceholder("空间名称，例如 客服制度知识")
    .fill("E2E 知识空间");
  await dialog.getByRole("button").last().click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    code: "e2e_space",
    name: "E2E 知识空间",
  });
});

test("新建知识文档按钮提交标题与空间", async ({ page }) => {
  await mockKnowledgeBase(page);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/knowledge-documents"),
  );
  await page.route("**/api/v1/knowledge-documents", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        ...document,
        title: "E2E 新文档",
      }),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/documents");
  await page.getByRole("button", { name: "新建文档" }).click();
  const dialog = page.getByRole("dialog", { name: "新建知识文档" });
  await dialog.getByPlaceholder("文档标题").fill("E2E 新文档");
  await dialog.locator(".ant-select").nth(1).click();
  await page
    .getByText("E2E 知识空间 · e2e_space", { exact: true })
    .last()
    .click();
  await dialog.getByRole("button").last().click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    title: "E2E 新文档",
    space_id: spaceId,
  });
});

test("新建文本知识版本按钮提交版本和正文", async ({ page }) => {
  await mockKnowledgeBase(page);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/knowledge-documents/${documentId}/versions`,
      ),
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/documents");
  await page.getByRole("button", { name: "E2E 文档" }).click();
  await page.getByRole("button", { name: "新建文本版本" }).click();
  const dialog = page.getByRole("dialog", {
    name: "新建文本知识版本",
  });
  await dialog.getByPlaceholder("版本号").fill("2.0");
  await dialog
    .getByPlaceholder("输入 SOP、FAQ 或制度正文")
    .fill("E2E 文本知识正文");
  await dialog.getByRole("button").last().click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    version_label: "2.0",
    content: "E2E 文本知识正文",
  });
});

test("新建评测案例按钮提交预期文档", async ({ page }) => {
  await mockKnowledgeBase(page);
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/knowledge/evaluation-cases"),
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
          id: "e2e-evaluation-case",
          knowledge_space_id: spaceId,
          employee_id: null,
          name: "E2E 评测",
          query: "保温杯材质",
          expected_titles: ["E2E 文档"],
          expect_no_grounding: false,
          scope: {},
          status: "ACTIVE",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/evaluation");
  await page.getByRole("button", { name: "新建评测案例" }).click();
  const dialog = page.getByRole("dialog", {
    name: "新建知识评测案例",
  });
  await dialog
    .getByPlaceholder("案例名称，例如 制度条款召回")
    .fill("E2E 评测");
  await dialog.locator(".ant-select").click();
  await page
    .getByText("E2E 知识空间 · e2e_space", { exact: true })
    .last()
    .click();
  const inputs = dialog.locator("textarea");
  await inputs.nth(0).fill("保温杯材质");
  await inputs.nth(1).fill("E2E 文档");
  await expect(inputs.nth(0)).toHaveValue("保温杯材质");
  await expect(inputs.nth(1)).toHaveValue("E2E 文档");
  await dialog.getByRole("button").last().click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    knowledge_space_id: spaceId,
    name: "E2E 评测",
    query: "保温杯材质",
    expected_titles: ["E2E 文档"],
  });
});
