import { expect, test, type Page } from "@playwright/test";

const now = new Date().toISOString();
const product = {
  id: "product-e2e",
  business_unit_id: "bu_demo",
  sku: "E2E-CUP-001",
  name: "E2E 保温杯",
  category: "保温杯",
  brand: "E2E 品牌",
  price: 88,
  attributes: { 容量: "480ml", 材质: "316不锈钢" },
  status: "READY",
  created_by: "e2e-agent",
  created_at: now,
  updated_at: now,
};

const category = {
  id: "category-e2e",
  business_unit_id: "bu_demo",
  code: "vacuum_cup",
  name: "保温杯",
  description: "E2E 品类",
  channel: "ecommerce_demo",
  required_attributes: ["容量", "材质"],
  presales_keywords: ["保温"],
  aftersales_keywords: ["漏水"],
  restricted_claims: ["国家级认证"],
  visual_requirements: {},
  status: "ACTIVE",
  created_at: now,
  updated_at: now,
};

const listingEmployee = {
  id: "employee-listing-e2e",
  employee_key: "ecommerce_listing_operator_e2e",
  name: "商品上架数字员工",
  version: "1.0.0",
  scenario_type: "ecommerce_operations",
  domain: "ecommerce_operations",
  template_code: "ecommerce_listing_operator",
  workflow_key: "customer_service_ticket_v1",
  business_unit_id: "bu_demo",
  service_identity: "digital_employee.ecommerce_listing_operator_e2e",
  status: "ACTIVE",
  handoff_queue: "ECOMMERCE_LISTING_REVIEW",
  knowledge_policy: {},
  model_profile: {},
  tool_allowlist: ["knowledge.search", "draft.create"],
  manifest: {},
  activation_evaluation: {},
  activation_evaluated_at: now,
  config_revision: 1,
  created_at: now,
  updated_at: now,
};

const listing = {
  id: "listing-e2e",
  product_id: product.id,
  business_unit_id: "bu_demo",
  sku: product.sku,
  product_name: product.name,
  product_category: product.category,
  channel: "ecommerce_demo",
  market_code: "CN",
  owner_employee_id: listingEmployee.id,
  locale: "zh-CN",
  currency: "CNY",
  sale_price: product.price,
  status: "PENDING_REVIEW",
  risk_level: "R1",
  version: 1,
  human_reason: null,
  external_listing_id: null,
  content: {
    title: "E2E 保温杯 480ml",
    selling_points: ["316 不锈钢内胆", "保温 12 小时"],
    detail_description: "E2E 保温杯详情，容量 480ml。",
    short_video_script: [
      {
        second: "0-3",
        visual: "保温杯正面特写",
        line: "E2E 保温杯，简约耐用。",
      },
    ],
    hashtags: ["#保温杯", "#316不锈钢"],
  },
  compliance: {
    restricted_claims: [],
    rule_count: 2,
    checked: true,
    missing_product_image: false,
    required_attributes_missing: [],
    channel_required_attributes_missing: [],
    primary_image_visual_audit_status: "PASS",
  },
  citations: [
    {
      chunk_id: "chunk-e2e",
      document_id: "document-e2e",
      space_id: "space-e2e",
      title: "电商平台发布规则",
      version: "2.0",
    },
  ],
  generator_provider: "local",
  generator_model: "e2e",
  error_message: null,
  reviewed_by: null,
  reviewed_at: null,
  published_at: null,
  created_at: now,
  updated_at: now,
};

function imageAsset(
  id: string,
  visualStatus = "PASS",
  primary = false,
) {
  return {
    id,
    product_id: product.id,
    business_unit_id: "bu_demo",
    owner_employee_id: listingEmployee.id,
    asset_type: "IMAGE",
    filename: `${id}.png`,
    content_type: "image/png",
    size_bytes: 1024,
    status: "READY",
    metadata: {
      width: 1024,
      height: 1024,
      quality_score: 0.98,
      is_primary: primary,
      visual_audit_status: visualStatus,
    },
    created_by: "e2e-agent",
    created_at: now,
  };
}

async function mockEcommerceShell(page: Page): Promise<void> {
  await page.route(
    "**/api/v1/digital-employees?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([listingEmployee]),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/products?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([product]),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/categories?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([category]),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
    async (route) => {
      if (route.request().method() === "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [listing], total: 1 }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/listing-batch-jobs?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/image-generations?business_unit_id=bu_demo*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total_images: 0, estimated_cost: 0 }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/metrics?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          business_unit_id: "bu_demo",
          total_listings: 1,
          pending_review: 1,
          needs_human: 0,
          publishing: 0,
          published: 0,
          rejected: 0,
          failed: 0,
          publication_success_rate: 1,
          human_intervention_rate: 0,
          average_publish_seconds: 12,
          market_breakdown: { CN: 1 },
          video_jobs: 0,
          video_succeeded: 0,
          video_failed: 0,
          video_active: 0,
          video_success_rate: 1,
          average_render_seconds: null,
          generated_images: 0,
          estimated_image_cost: 0,
        }),
      });
    },
  );
}

async function openEcommerce(page: Page, path = "/ecommerce"): Promise<void> {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto(path);
  await expect(
    page.getByRole("heading", {
      name: "电商运营数字员工工作区",
      exact: true,
    }),
  ).toBeVisible();
}

test("上架任务显示实际负责的数字员工", async ({ page }) => {
  await mockEcommerceShell(page);
  await openEcommerce(page, "/ecommerce/listings");
  await expect(
    page.getByText("商品上架数字员工", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("负责数字员工", { exact: true }),
  ).toBeVisible();
});

test("品类档案按钮创建完整品类规则", async ({ page }) => {
  await mockEcommerceShell(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/ecommerce/categories"),
  );
  await page.route(
    "**/api/v1/ecommerce/categories",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          ...category,
          id: "category-created",
          code: "new_category",
          name: "新品类",
        }),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/products");
  await page.getByRole("button", { name: "品类档案" }).click();
  const dialog = page.getByRole("dialog", { name: "电商品类档案" });
  await dialog.getByPlaceholder("vacuum_cup").fill("new_category");
  await dialog.getByPlaceholder("保温杯").fill("新品类");
  await dialog.locator("textarea").nth(0).fill("容量，材质");
  await dialog.locator("textarea").nth(1).fill("保温,耐用");
  await dialog.locator("textarea").nth(2).fill("漏水,退换");
  await dialog.locator("textarea").nth(3).fill("国家级认证");
  await dialog.getByRole("button", { name: "创建品类档案" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    code: "new_category",
    name: "新品类",
    required_attributes: ["容量", "材质"],
    presales_keywords: ["保温", "耐用"],
    aftersales_keywords: ["漏水", "退换"],
    restricted_claims: ["国家级认证"],
  });
  await expect(page.getByText("品类档案已创建")).toBeVisible();
});

test("创建上架任务按钮提交商品、市场和渠道", async ({ page }) => {
  await mockEcommerceShell(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().includes("/api/v1/ecommerce/listing-tasks"),
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
    async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ ...listing, id: "listing-created" }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-created",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...listing, id: "listing-created" }),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/listings");
  await page.getByRole("button", { name: "创建上架任务" }).click();
  const dialog = page.getByRole("dialog", { name: "创建上架任务" });
  await dialog.locator(".ant-select").first().click();
  await page
    .getByText("E2E 保温杯 · E2E-CUP-001", { exact: true })
    .last()
    .click();
  await dialog.getByRole("button", { name: "生成上架内容" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    product_id: product.id,
    market_code: "CN",
    channel: "local_shop",
    sale_price: product.price,
  });
  await expect(page.getByText("上架内容已生成")).toBeVisible();
});

test("批量生成上架按钮最多提交选中的商品", async ({ page }) => {
  await mockEcommerceShell(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/ecommerce/listing-batch-jobs"),
  );
  await page.route(
    "**/api/v1/ecommerce/listing-batch-jobs",
    async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          id: "batch-e2e",
          business_unit_id: "bu_demo",
          channel: "local_shop",
          market_code: "CN",
          status: "QUEUED",
          total_count: 1,
          succeeded_count: 0,
          failed_count: 0,
          error_message: null,
          created_by: "e2e-agent",
          created_at: now,
          started_at: null,
          completed_at: null,
          items: [],
        }),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/listings");
  await page.getByRole("button", { name: "批量生成上架" }).click();
  const dialog = page.getByRole("dialog", { name: "批量生成上架任务" });
  await dialog.locator(".ant-select").first().click();
  await page
    .getByText("E2E 保温杯 · E2E-CUP-001", { exact: true })
    .last()
    .click();
  await dialog.getByRole("button", { name: "提交批量任务" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    product_ids: [product.id],
    channel: "local_shop",
    market_code: "CN",
  });
  await expect(page.getByText("批量任务已提交，共 1 个商品")).toBeVisible();
});

test("CSV 导入先预览再确认导入有效行", async ({ page }) => {
  await mockEcommerceShell(page);
  let importedCsv = "";
  await page.route(
    "**/api/v1/ecommerce/products/import/preview?*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total_rows: 1,
          valid_rows: 1,
          invalid_rows: 0,
          rows: [
            {
              row_number: 1,
              sku: "CSV-E2E-001",
              name: "CSV 保温杯",
              category: "保温杯",
              valid: true,
              errors: [],
            },
          ],
        }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/products/import?*",
    async (route) => {
      importedCsv = route.request().postData() ?? "";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          created_count: 1,
          skipped_count: 0,
          products: [product],
          errors: [],
        }),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/products");
  await page.getByRole("button", { name: "批量导入 CSV" }).click();
  const dialog = page.getByRole("dialog", { name: "批量导入商品" });
  const csv = "sku,name,category,price\nCSV-E2E-001,CSV 保温杯,保温杯,59";
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "products.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  await expect(dialog.getByText("可导入 1")).toBeVisible();
  await dialog.getByRole("button", { name: "确认导入有效行" }).click();
  await expect.poll(() => importedCsv).toBe(csv);
  await expect(page.getByText("导入完成：创建 1 个，跳过 0 个")).toBeVisible();
});

test("下载 CSV 模板按钮请求模板文件", async ({ page }) => {
  await mockEcommerceShell(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "GET" &&
      request.url().endsWith("/api/v1/ecommerce/products/import-template"),
  );
  await page.route(
    "**/api/v1/ecommerce/products/import-template",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/csv",
        headers: {
          "Content-Disposition": 'attachment; filename="products.csv"',
        },
        body: "sku,name,category,price\n",
      });
    },
  );
  await openEcommerce(page, "/ecommerce/products");
  await page.getByRole("button", { name: "批量导入 CSV" }).click();
  await page.getByRole("button", { name: "下载 CSV 模板" }).click();
  await requestPromise;
});

test("编辑上架内容和下载上架包均提交当前任务版本", async ({ page }) => {
  await mockEcommerceShell(page);
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(listing),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/products/product-e2e/assets?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/video-render-jobs?limit=20",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0 }),
      });
    },
  );
  const packagePromise = page.waitForRequest(
    (request) =>
      request.method() === "GET" &&
      request.url().endsWith(
        "/api/v1/ecommerce/listing-tasks/listing-e2e/export",
      ),
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/export",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        body: Buffer.from("PK-e2e-zip"),
      });
    },
  );
  const editPromise = page.waitForRequest(
    (request) =>
      request.method() === "PATCH" &&
      request.url().endsWith(
        "/api/v1/ecommerce/listing-tasks/listing-e2e/content",
      ),
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/content",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(listing),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/listings?listing=listing-e2e");
  await expect(page.getByText("上架任务 · E2E 保温杯")).toBeVisible();
  await page.getByRole("button", { name: "下载上架包" }).click();
  await packagePromise;
  await page.getByRole("button", { name: "编辑内容" }).click();
  const dialog = page.getByRole("dialog", { name: "编辑上架内容" });
  await dialog.locator(".ant-input").nth(0).fill("E2E 保温杯 480ml 升级版");
  await dialog.locator("textarea").nth(0).fill(
    "316 不锈钢内胆\n保温 12 小时\n480ml 容量",
  );
  await dialog.locator("textarea").nth(1).fill("更新后的商品详情。");
  await dialog.getByRole("button", { name: "保存并重新检查" }).click();
  const request = await editPromise;
  expect(request.postDataJSON()).toMatchObject({
    expected_version: 1,
    title: "E2E 保温杯 480ml 升级版",
    selling_points: ["316 不锈钢内胆", "保温 12 小时", "480ml 容量"],
    detail_description: "更新后的商品详情。",
  });
});

test("素材主图、视觉确认和归档按钮完成素材治理", async ({ page }) => {
  await mockEcommerceShell(page);
  let assets = [
    imageAsset("asset-primary", "PASS", true),
    imageAsset("asset-review", "NEEDS_REVIEW", false),
  ];
  await page.route(
    "**/api/v1/ecommerce/products/product-e2e/assets?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(assets),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/products/product-e2e/assets*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(assets),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/assets/asset-review/primary",
    async (route) => {
      assets = assets.map((asset) => ({
        ...asset,
        metadata: { ...asset.metadata, is_primary: asset.id === "asset-review" },
      }));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(assets[1]),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/assets/asset-review/visual-review/accept",
    async (route) => {
      assets = assets.map((asset) =>
        asset.id === "asset-review"
          ? {
              ...asset,
              metadata: {
                ...asset.metadata,
                visual_audit_status: "ACCEPTED",
              },
            }
          : asset,
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(assets[1]),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/assets/asset-review/archive",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...assets[1], status: "ARCHIVED" }),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/assets/*/content",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    },
  );
  await openEcommerce(page, "/ecommerce/products");
  await page.getByRole("button", { name: "素材" }).click();
  const drawer = page.getByRole("dialog", { name: "商品素材 · E2E 保温杯" });
  await expect(drawer.getByText("asset-review.png")).toBeVisible();
  await drawer.getByRole("button", { name: "设为主图" }).click();
  await expect(page.getByText("已设为商品主图")).toBeVisible();
  await drawer.getByRole("button", { name: "确认视觉可用" }).click();
  await expect(page.getByText("已确认图片视觉可用")).toBeVisible();
  await drawer.getByRole("button", { name: /^归\s*档$/ }).last().click();
  const confirm = page.getByRole("dialog", { name: "归档该素材？" });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: /^归\s*档$/ }).click();
  await expect(page.getByText("素材已归档")).toBeVisible();
});

test("分镜生成、视频渲染失败后可重试", async ({ page }) => {
  await mockEcommerceShell(page);
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(listing),
      });
    },
  );
  let storyboardGenerated = false;
  const storyboardAsset = {
    ...imageAsset("storyboard-e2e", "PASS"),
    metadata: {
      ...imageAsset("storyboard-e2e", "PASS").metadata,
      listing_task_id: listing.id,
      source: "STORYBOARD_GENERATED",
      scene_index: 1,
      scene_seconds: 3,
      scene_visual: "保温杯正面特写",
      scene_line: "E2E 保温杯。",
    },
  };
  await page.route(
    "**/api/v1/ecommerce/products/product-e2e/assets?business_unit_id=bu_demo",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(storyboardGenerated ? [storyboardAsset] : []),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/products/product-e2e/assets*",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(storyboardGenerated ? [storyboardAsset] : []),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/assets/*/content",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    },
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/storyboard/generate",
    async (route) => {
      storyboardGenerated = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [storyboardAsset] }),
      });
    },
  );
  let failedJob = false;
  const renderJob = {
    id: "render-e2e",
    business_unit_id: "bu_demo",
    product_id: product.id,
    listing_task_id: listing.id,
    generation_id: "generation-e2e",
    status: "FAILED",
    progress: 100,
    scene_count: 1,
    duration_seconds: 3,
    asset_id: null,
    background_music_asset_id: null,
    background_music_volume: 0.18,
    error_message: "FFmpeg 渲染失败",
    correlation_id: "e2e-render",
    created_by: "e2e-agent",
    retry_count: 0,
    created_at: now,
    started_at: now,
    completed_at: now,
    updated_at: now,
  };
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/video-render-jobs?limit=20",
    async (route) => {
      const items = failedJob ? [renderJob] : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items, total: items.length }),
      });
    },
  );
  const createJobPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/ecommerce/listing-tasks/listing-e2e/storyboard/video-jobs",
      ),
  );
  await page.route(
    "**/api/v1/ecommerce/listing-tasks/listing-e2e/storyboard/video-jobs",
    async (route) => {
      failedJob = true;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(renderJob),
      });
    },
  );
  const retryPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith(
        "/api/v1/ecommerce/video-render-jobs/render-e2e/retry",
      ),
  );
  await page.route(
    "**/api/v1/ecommerce/video-render-jobs/render-e2e/retry",
    async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ ...renderJob, status: "QUEUED", progress: 0 }),
      });
    },
  );
  await openEcommerce(
    page,
    "/ecommerce/listings?listing=listing-e2e&video=1",
  );
  await page.getByRole("button", { name: "生成分镜图" }).click();
  await expect(page.getByText("短视频分镜图已生成")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "生成竖屏预览" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "生成竖屏预览" }).click();
  const createJob = await createJobPromise;
  expect(createJob.postDataJSON()).toEqual({
    background_music_asset_id: null,
    background_music_volume: 0.18,
  });
  await expect(page.getByText("视频渲染失败，可直接重试")).toBeVisible();
  await page.getByRole("button", { name: "重试渲染" }).click();
  await retryPromise;
  await expect(page.getByText(/渲染任务已重新提交/)).toBeVisible();
});

test("商品知识同步按钮归属电商模块并显示同步统计", async ({ page }) => {
  await mockEcommerceShell(page);
  const requestPromise = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/api/v1/knowledge/product-sync"),
  );
  await page.route("**/api/v1/knowledge/product-sync", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        business_unit_id: "bu_demo",
        requested: 3,
        synced: 2,
        unchanged: 1,
        failed: 0,
        items: [],
      }),
    });
  });
  await openEcommerce(page, "/ecommerce/products");
  await page.getByRole("button", { name: "同步商品知识" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toEqual({
    business_unit_id: "bu_demo",
    product_ids: [],
  });
  await expect(
    page.getByText("商品知识同步完成：更新 2，未变化 1，失败 0"),
  ).toBeVisible();
});
