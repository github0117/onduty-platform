import { expect, test } from "@playwright/test";

test("新增商品按钮提交完整商品资料", async ({ page }) => {
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/api/v1/ecommerce/products"),
  );
  await page.route("**/api/v1/ecommerce/products", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: "e2e-product",
        sku: "E2E-SKU-001",
        name: "E2E 测试商品",
        category: "家居日用",
        brand: "演示品牌",
        price: 39.9,
        status: "READY",
        attributes: { 材质: "食品级硅胶" },
      }),
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/ecommerce/products");
  await page.getByRole("button", { name: "新增商品" }).click();
  const dialog = page.getByRole("dialog", { name: "新增商品" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("SKU").fill("E2E-SKU-001");
  await dialog.getByLabel("商品名称").fill("E2E 测试商品");
  await dialog.getByRole("button", { name: "创建商品" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    business_unit_id: "bu_demo",
    sku: "E2E-SKU-001",
    name: "E2E 测试商品",
    category: "家居日用",
    brand: "演示品牌",
    price: 39.9,
  });
});

test("批量导入按钮打开导入弹窗", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/ecommerce/products");
  await page.getByRole("button", { name: "批量导入 CSV" }).click();
  await expect(
    page.getByRole("dialog", { name: "批量导入商品" }),
  ).toBeVisible();
});

test("AI 主图按钮提交图片生成参数", async ({ page }) => {
  await page.route(
    "**/api/v1/ecommerce/products/*/assets/generate-batch",
    async (route) => {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
        }),
      });
    },
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/ecommerce/products");
  await page.getByRole("button", { name: "AI 主图" }).first().click();
  const dialog = page.getByRole("dialog", { name: /AI 生成主图/ });
  await expect(dialog).toBeVisible();
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith("/assets/generate-batch"),
  );
  await dialog.getByRole("button", { name: "生成主图" }).click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    prompt: expect.stringContaining("产品质感"),
    count: 3,
  });
});
