import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { test, type Page } from "@playwright/test";

// README 截图是有意生成、手工挑选的文档资产，不在每次 CI 回归里重跑。
// 需要更新时：
//   docker compose -f infra/compose/docker-compose.yml --profile app \
//     run --rm -e CAPTURE_DOCS=1 -e E2E_ARGS=docs-screenshots e2e
const captureDocs = process.env.CAPTURE_DOCS === "1";
const screenshotDir = resolve("test-results/docs");

const pages = [
  { path: "/customer-service?scenario=enterprise", name: "customer-service-enterprise" },
  { path: "/tickets", name: "tickets" },
  { path: "/customer-service/workbench", name: "customer-service" },
  { path: "/knowledge/documents", name: "knowledge" },
  { path: "/ecommerce/listings", name: "ecommerce" },
  { path: "/employees/roster", name: "employees" },
];

async function prepare(page: Page, path: string): Promise<void> {
  // 工作台默认只看“我的”，截图切到“全部”并打开一条会话，避免空列表。
  if (path !== "/customer-service/workbench") return;
  await page.locator(".workbench-list").getByText("全部", { exact: true }).click();
  const conversation = page.locator(".workbench-conversation-item").first();
  if (await conversation.count()) {
    await conversation.click();
    await page.waitForTimeout(1200);
  }
}

test("capture curated documentation screenshots", async ({ page }) => {
  test.skip(!captureDocs, "set CAPTURE_DOCS=1 to refresh docs screenshots");

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
  await page.setViewportSize({ width: 1440, height: 900 });
  mkdirSync(screenshotDir, { recursive: true });

  for (const item of pages) {
    await page.goto(item.path);
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await page.waitForTimeout(1500);
    await prepare(page, item.path);
    await page.screenshot({
      path: resolve(screenshotDir, `${item.name}.png`),
    });
  }

  await page.goto("/employees/roster");
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page
    .getByRole("button", { name: "HR 入职资料数字员工", exact: true })
    .first()
    .click();
  await page.waitForTimeout(1200);
  await page.screenshot({
    path: resolve(screenshotDir, "employee-snapshot.png"),
  });

  await page.goto("/employees/routing");
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.waitForTimeout(1500);
  await page.screenshot({
    path: resolve(screenshotDir, "employee-routing.png"),
  });
});
