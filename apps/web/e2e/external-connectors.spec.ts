import { expect, test, type Page } from "@playwright/test";

import { useIdentity } from "./helpers/identity";

const connectorKey = `ui-orders-${Date.now()}`;

// Ant Design inserts a space between two CJK characters in buttons.
const label = (text: string) => new RegExp(text.split("").join("\\s*"));

async function openHttpConnectorEditor(page: Page): Promise<void> {
  await page.getByRole("button", { name: "新建外部连接" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByPlaceholder("support-mail").fill(connectorKey);
  await dialog.getByPlaceholder("客服支持邮箱").fill("UI 订单只读连接");
  await dialog.getByText("邮件（IMAP + SMTP）").click();
  await page.getByText("只读 HTTP JSON", { exact: true }).click();
}

test("平台管理员可在页面创建、检测并查询只读外部连接", async ({ page }) => {
  await useIdentity(page, "platform-admin");
  await page.goto("/employees/integrations");

  await expect(
    page.getByText("外部连接 · 邮件与只读业务系统"),
  ).toBeVisible();
  await expect(page.getByText("MCP · 工具型业务系统连接")).toBeVisible();

  await openHttpConnectorEditor(page);
  const dialog = page.getByRole("dialog");
  await dialog
    .getByPlaceholder("https://orders.example.com")
    .fill("http://mock-business:8090");
  await dialog.getByPlaceholder("/api/orders").fill("/orders/O-1001");
  await dialog.getByRole("button", { name: label("保存") }).click();

  await expect(page.getByText("外部连接已创建")).toBeVisible();
  const row = page.getByRole("row", { name: new RegExp(connectorKey) });
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: label("检测") }).click();
  await expect(page.getByText("连接正常：Health endpoint returned 200.")).toBeVisible();
  await expect(row.getByText("正常")).toBeVisible();

  await row.getByRole("button", { name: label("查询") }).click();
  const drawer = page.getByRole("dialog");
  await drawer.getByRole("button", { name: "执行查询" }).click();
  await expect(page.getByText("查询成功（HTTP 200）")).toBeVisible();
  await expect(drawer.locator("pre")).toContainText("O-1001");
  await drawer.press("Escape");

  // 重复编码：真实 409 必须给出可理解的提示，而不是静默或误报成功。
  await openHttpConnectorEditor(page);
  const duplicateDialog = page.getByRole("dialog");
  await duplicateDialog
    .getByPlaceholder("https://orders.example.com")
    .fill("http://mock-business:8090");
  await duplicateDialog.getByRole("button", { name: label("保存") }).click();
  await expect(
    page.getByText("连接器编码已存在，请换一个编码后重试。"),
  ).toBeVisible();
});

test("审计员可直接访问外部连接页，但看不到任何写入口", async ({ page }) => {
  await useIdentity(page, "auditor");
  await page.goto("/employees/integrations");

  await expect(
    page.getByText("外部连接 · 邮件与只读业务系统"),
  ).toBeVisible();
  await expect(page.getByText("MCP · 工具型业务系统连接")).toBeVisible();
  await expect(page.getByRole("button", { name: "新建外部连接" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "新建 MCP 连接器" })).toHaveCount(
    0,
  );

  const row = page.getByRole("row", { name: new RegExp(connectorKey) });
  await expect(row).toBeVisible();
  await expect(row.getByText("只读", { exact: true })).toBeVisible();
  await expect(row.getByRole("button", { name: label("编辑") })).toHaveCount(0);
  await expect(row.getByRole("button", { name: label("检测") })).toHaveCount(0);
});
