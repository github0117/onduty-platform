import { expect, test } from "@playwright/test";

const entries = [
  {
    path: "/knowledge/spaces",
    heading: "知识库 · 知识空间",
    primary: "新建知识空间",
    absent: "运行全部评测",
  },
  {
    path: "/knowledge/documents",
    heading: "知识库 · 知识文档",
    primary: "新建文档",
    absent: "运行全部评测",
  },
  {
    path: "/knowledge/search",
    heading: "知识库 · 检索调试",
    primary: "检 索",
    absent: "新建文档",
  },
  {
    path: "/knowledge/evaluation",
    heading: "知识库 · 质量评测",
    primary: "新建评测案例",
    absent: "批量导入 FAQ CSV",
  },
  {
    path: "/knowledge/repairs",
    heading: "知识库 · 修复与反馈",
    primary: "知识修复队列",
    absent: "运行全部评测",
  },
];

test("知识库总览只展示统计和二级入口", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge");
  await expect(
    page.getByRole("heading", { name: "知识库工作台" }),
  ).toBeVisible();
  await expect(page.getByText("推荐操作顺序")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "管理知识空间" }),
  ).toBeVisible();
  await expect(page.getByText(/知识来源包括制度、SOP、FAQ/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "运行全部评测" }),
  ).toHaveCount(0);

  await page.getByRole("button", { name: "管理知识文档" }).click();
  await expect(page).toHaveURL(/\/knowledge\/documents$/);
  await expect(
    page.getByRole("heading", { name: "知识库 · 知识文档" }),
  ).toBeVisible();
});

test("知识库二级页面可直接访问且每个页面只保留主任务", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  for (const entry of entries) {
    await page.goto(entry.path);
    await expect(
      page.getByRole("heading", { name: entry.heading }),
    ).toBeVisible();
    const primary =
      entry.primary === "知识修复队列"
        ? page.getByText(entry.primary, { exact: true })
        : page.getByRole("button", { name: entry.primary });
    await expect(primary.first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: entry.absent }),
    ).toHaveCount(0);
  }
});

test("知识库使用通用来源且不再展示电商专用同步按钮", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/spaces");
  await expect(
    page.getByText("知识空间是资料归属，不代表资料来源"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "同步商品知识" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "知识空间状态" }),
  ).toBeVisible();
  await expect(
    page.getByText("企业服务制度与流程", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("客户服务 SOP 与 FAQ", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("IT、账号与权限制度", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("HR 入职与员工服务", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/真实修复验收空间/),
  ).toHaveCount(0);

  await page.goto("/knowledge/documents");
  await expect(page.getByText("通用知识从这里接入")).toBeVisible();
  await expect(
    page.getByText("制度与业务规则", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("SOP、FAQ 与客服问答", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "批量导入 FAQ CSV" }),
  ).toBeVisible();
  await expect(
    page.getByText("外部知识源", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "同步商品知识" }),
  ).toHaveCount(0);
});

test("知识文档和版本状态使用中文，不直接显示内部代码", async ({
  page,
}) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/spaces");
  await expect(page.getByText("可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("ACTIVE", { exact: true })).toHaveCount(0);

  await page.goto("/knowledge/documents");
  await expect(page.getByText("可用", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("ACTIVE", { exact: true })).toHaveCount(0);
  const firstDocument = page
    .getByRole("table")
    .filter({ hasText: "来源同步" })
    .getByRole("button")
    .first();
  await firstDocument.click();
  await expect(
    page.getByText("版本管理", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText(/ACTIVE|SUPERSEDED|RETIRED/, { exact: true }),
  ).toHaveCount(0);
});

test("知识评测默认只展示当前启用案例", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/evaluation");
  await expect(
    page.getByRole("combobox", { name: "评测案例范围" }),
  ).toBeVisible();
  await expect(
    page.getByText("当前启用", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("已停用", { exact: true }),
  ).toHaveCount(0);
});

test("知识文档默认隐藏验收测试空间的资料", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/knowledge/documents");

  await expect(
    page.getByText(/真实修复验收空间/),
  ).toHaveCount(0);
  await expect(
    page.getByText(/验收退款知识/),
  ).toHaveCount(0);
});
