import { expect, test } from "@playwright/test";

const spaceId = "e2e-knowledge-space";
const documentId = "e2e-knowledge-document";
const versionId = "e2e-knowledge-version";

test("知识版本发布按钮提交文档和版本", async ({ page }) => {
  const now = new Date().toISOString();
  const space = {
    id: spaceId,
    business_unit_id: "bu_demo",
    code: "e2e_space",
    name: "E2E 知识空间",
    description: "测试知识空间",
    domain: "customer_service",
    channel: "ecommerce_demo",
    category: "保温杯",
    category_profile_id: null,
    workflow_key: "customer_service_ticket_v1",
    owner_id: "e2e-admin",
    evaluation_required: false,
    status: "ACTIVE",
    document_count: 1,
    created_at: now,
    updated_at: now,
  };
  const document = {
    id: documentId,
    space_id: spaceId,
    business_unit_id: "bu_demo",
    title: "E2E 商品知识",
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
    created_at: now,
    updated_at: now,
  };
  const version = {
    id: versionId,
    document_id: documentId,
    version_label: "1.0",
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
    processing_started_at: null,
    processed_at: now,
    chunk_count: 2,
    published_at: null,
    created_at: now,
  };
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
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([version]),
      });
    },
  );
  await page.route(
    `**/api/v1/knowledge-documents/${documentId}/versions/${versionId}/publish`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...version, status: "ACTIVE" }),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/documents");
  await page.getByRole("button", { name: "E2E 商品知识" }).click();
  await expect(
    page.getByText("版本管理 · E2E 商品知识"),
  ).toBeVisible();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/knowledge-documents/${documentId}/versions/${versionId}/publish`,
      ),
  );
  await page.getByRole("button", { name: /^发\s*布$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    release_note: "Published from workbench",
  });
});

test("知识检索按钮提交问题并显示召回结果", async ({ page }) => {
  await page.route("**/api/v1/knowledge/search", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            chunk_id: "e2e-hit",
            document_id: documentId,
            space_id: spaceId,
            title: "E2E 商品知识",
            version: "1.0",
            content: "316 不锈钢内胆，保温约 12 小时。",
            score: 0.93,
          },
        ],
        embedding_model: "local",
        reranker: "local-hybrid",
      }),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/search");
  const searchInput = page.getByPlaceholder("输入业务问题");
  await searchInput.fill("保温杯材质");
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/knowledge/search"),
  );
  await page.getByRole("button", { name: /^检\s*索$/ }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    query: "保温杯材质",
  });
  await expect(
    page.getByText("316 不锈钢内胆，保温约 12 小时。"),
  ).toBeVisible();
});
