import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const screenshotDir = resolve("test-results/pilot");

async function useIdentity(
  page: Page,
  profileId: string,
  businessUnit = "bu_demo",
): Promise<void> {
  await page.addInitScript(
    ({ profileId, businessUnit }) => {
      window.localStorage.clear();
      window.localStorage.setItem(
        "digital-workforce:test-identity",
        profileId,
      );
      window.localStorage.setItem(
        "digital-workforce:test-business-unit",
        businessUnit,
      );
    },
    { profileId, businessUnit },
  );
}

async function capture(page: Page, name: string): Promise<void> {
  mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({
    path: resolve(screenshotDir, `${name}.png`),
    fullPage: true,
  });
}

test("客服坐席可从角色首页进入工作台", async ({ page }) => {
  await useIdentity(page, "service-agent");
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service\/workbench$/);
  await expect(
    page.getByRole("heading", { name: "人工客服工作台" }),
  ).toBeVisible();
  await expect(
    page.getByText("平台管理", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "管理员视图" }),
  ).toHaveCount(0);
  await capture(page, "01-service-agent");
});

test("客服主管可从角色首页进入运营看板", async ({ page }) => {
  await useIdentity(page, "service-supervisor");
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service\/admin$/);
  await expect(
    page.getByRole("heading", { name: "运营看板" }),
  ).toBeVisible();
  await expect(
    page.getByText("这三个页面分别做什么", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("客户服务测试入口", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("会话列表", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("经营品类", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("运行与审计", { exact: true }),
  ).toBeVisible();
  await capture(page, "02-service-supervisor");
});

test("知识运营可从角色首页进入知识文档", async ({ page }) => {
  await useIdentity(page, "knowledge-operator");
  await page.goto("/");

  await expect(page).toHaveURL(/\/knowledge\/documents$/);
  await expect(
    page.getByRole("heading", { name: "知识库工作台" }),
  ).toBeVisible();
  await expect(
    page.getByText("已归档", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("员工、Skill 与 MCP", { exact: true }),
  ).toBeVisible();
  await capture(page, "03-knowledge-operator");
});

test("业务经理可从角色首页查看跨场景指标", async ({ page }) => {
  await useIdentity(page, "business-manager");
  await page.goto("/");

  await expect(page).toHaveURL(/\/overview$/);
  await expect(
    page.getByRole("heading", {
      name: "研发支持 Agent：从 RAG 到真实 MCP 工具调用",
    }),
  ).toBeVisible();
  const enabledEmployees = page
    .locator(".ant-statistic")
    .filter({ hasText: "已上岗员工" });
  await expect(enabledEmployees).toBeVisible();
  await expect(
    enabledEmployees.locator(".ant-statistic-content-value"),
  ).not.toHaveText("0");
  await expect(
    page.getByText("员工、Skill 与 MCP", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "检查并恢复演示数据" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "直接进入主演示" }),
  ).toBeVisible();
  await capture(page, "04-business-manager");
});

test("平台管理员可进入完整员工配置", async ({ page }) => {
  await useIdentity(page, "platform-admin");
  await page.goto("/employees/roster");

  await expect(
    page.getByRole("heading", { name: "数字员工名单" }),
  ).toBeVisible();
  await expect(
    page.getByText("Skill（岗位规程）", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("模型与连接", { exact: true }),
  ).toBeVisible();
  await capture(page, "05-platform-admin");
});
