import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { useIdentity } from "./helpers/identity";

const screenshotDir = resolve("test-results/pilot");

async function capture(page: Page, name: string): Promise<void> {
  mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({
    path: resolve(screenshotDir, `${name}.png`),
    fullPage: true,
  });
}

test("客服坐席可从角色首页进入主演示", async ({ page }) => {
  await useIdentity(page, "service-agent");
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service$/);
  await expect(
    page.getByRole("heading", { name: "像员工一样问，自动分派给对的人" }),
  ).toBeVisible();
  await expect(
    page.getByRole("menuitem", { name: "主管看板", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("menuitem", { name: "运行与审计", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "管理员视图" }),
  ).toHaveCount(0);
  await capture(page, "01-service-agent");
});

test("客服主管可从角色首页进入运营看板", async ({ page }) => {
  await useIdentity(page, "service-supervisor");
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service$/);
  await page.getByRole("menuitem", { name: "主管看板", exact: true }).click();
  await expect(page).toHaveURL(/\/customer-service\/admin$/);
  await expect(
    page.getByRole("heading", { name: "运营看板", exact: true }),
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

  await expect(page).toHaveURL(/\/operations$/);
  await expect(
    page.getByRole("heading", { name: "运行与审计", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("员工、Skill 与 MCP", { exact: true }),
  ).toBeVisible();

  await page.goto("/knowledge/documents");
  await expect(page).toHaveURL(/\/knowledge\/documents$/);
  await expect(
    page.getByRole("heading", { name: "知识库工作台" }),
  ).toBeVisible();
  await expect(
    page.getByText("已归档", { exact: true }),
  ).toHaveCount(0);
  await capture(page, "03-knowledge-operator");
});

test("业务经理可从角色首页查看运行与审计指标", async ({ page }) => {
  await useIdentity(page, "business-manager");
  await page.goto("/");

  await expect(page).toHaveURL(/\/operations$/);
  await expect(
    page.getByRole("heading", { name: "运行与审计", exact: true }),
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
    page.getByRole("menuitem", { name: "企业服务台 Agent", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("menuitem", { name: "内部工单 / HR", exact: true }),
  ).toBeVisible();

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByRole("heading", { name: "待审批操作", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批并执行" }),
  ).toHaveCount(0);
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
