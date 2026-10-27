import { expect, test, type Page } from "@playwright/test";

import { useIdentity } from "./helpers/identity";

const navItem = (page: Page, name: string) =>
  page.getByRole("menuitem", { name, exact: true });

async function mockPendingApproval(page: Page): Promise<void> {
  await page.route("**/api/v1/mcp/tool-approvals**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        total: 1,
        items: [
          {
            id: "approval-capability-test",
            tool_id: "mcp.demo.write",
            arguments: { order_id: "DEMO-1" },
            status: "PENDING",
            reason: "权限契约演示",
            required_role: "supervisor",
            requested_by: "demo.agent",
            decided_by: null,
            decision_note: null,
            error_message: null,
            result: {},
            ticket_id: null,
            conversation_id: null,
            created_at: "2026-10-27T00:00:00Z",
          },
        ],
      }),
    }),
  );
}

test("客服坐席只看到对话、工单和知识入口，写操作随能力出现", async ({
  page,
}) => {
  await useIdentity(page, "service-agent");
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service$/);
  await expect(navItem(page, "企业服务台 Agent")).toBeVisible();
  await expect(navItem(page, "人工工作台")).toBeVisible();
  await expect(navItem(page, "电商运营复用")).toBeVisible();
  await expect(navItem(page, "内部工单 / HR")).toBeVisible();
  await expect(navItem(page, "知识与评测")).toBeVisible();
  await expect(navItem(page, "员工、Skill 与 MCP")).toHaveCount(0);
  await expect(navItem(page, "运行与审计")).toHaveCount(0);
  await expect(navItem(page, "模型与连接")).toHaveCount(0);
  await expect(navItem(page, "平台总览")).toHaveCount(0);

  await page.goto("/ecommerce/products");
  await expect(
    page.getByRole("heading", { name: "电商运营数字员工工作区" }),
  ).toBeVisible();
  await expect(page.getByText("当前角色为只读访问")).toBeVisible();
  await expect(page.getByRole("button", { name: "新增商品" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "品类档案" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "批量导入 CSV" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "同步商品知识" }),
  ).toHaveCount(0);

  await page.goto("/tickets");
  await expect(
    page.getByRole("button", { name: "创建演示工单" }),
  ).toBeVisible();

  await page.goto("/customer-service/admin");
  await expect(page.getByText("当前身份无权访问此页面")).toBeVisible();
});

test("客服主管可审批、处理异常和创建上架任务", async ({ page }) => {
  await useIdentity(page, "service-supervisor");
  await mockPendingApproval(page);
  await page.goto("/");

  await expect(page).toHaveURL(/\/customer-service$/);
  await expect(navItem(page, "主管看板")).toBeVisible();
  await expect(navItem(page, "写操作审批")).toBeVisible();
  await expect(navItem(page, "执行异常")).toBeVisible();

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByRole("heading", { name: "待审批操作", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批并执行" }),
  ).toBeVisible();

  await page.goto("/ecommerce/listings");
  await expect(
    page.getByRole("button", { name: "创建上架任务" }),
  ).toBeVisible();

  await page.goto("/operations");
  await expect(
    page.getByRole("button", { name: "检查并恢复演示数据" }),
  ).toHaveCount(0);
});

test("知识运营维护目录但不执行上架或审批", async ({ page }) => {
  await useIdentity(page, "knowledge-operator");
  await page.goto("/");

  await expect(page).toHaveURL(/\/operations$/);
  await expect(navItem(page, "员工、Skill 与 MCP")).toBeVisible();
  await expect(navItem(page, "知识与评测")).toBeVisible();
  await expect(navItem(page, "运行与审计")).toBeVisible();
  await expect(navItem(page, "企业服务台 Agent")).toHaveCount(0);
  await expect(navItem(page, "内部工单 / HR")).toHaveCount(0);
  await expect(navItem(page, "平台总览")).toHaveCount(0);

  await page.goto("/ecommerce/products");
  await expect(page.getByText("当前角色可维护商品目录")).toBeVisible();
  await expect(page.getByRole("button", { name: "新增商品" })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "批量导入 CSV" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "同步商品知识" }),
  ).toBeVisible();

  await page.goto("/ecommerce/listings");
  await expect(
    page.getByRole("button", { name: "创建上架任务" }),
  ).toHaveCount(0);

  await page.goto("/operations");
  await expect(
    page.getByRole("button", { name: "检查并恢复演示数据" }),
  ).toHaveCount(0);
});

test("业务经理只读查看审批、工单与运行数据", async ({ page }) => {
  await useIdentity(page, "business-manager");
  await mockPendingApproval(page);
  await page.goto("/");

  await expect(page).toHaveURL(/\/operations$/);
  await expect(navItem(page, "内部工单 / HR")).toBeVisible();
  await expect(navItem(page, "电商运营复用")).toBeVisible();
  await expect(navItem(page, "运行与审计")).toBeVisible();
  await expect(navItem(page, "企业服务台 Agent")).toHaveCount(0);
  await expect(navItem(page, "员工、Skill 与 MCP")).toHaveCount(0);

  await page.goto("/tickets");
  await expect(
    page.getByRole("button", { name: "创建演示工单" }),
  ).toHaveCount(0);
  await expect(page.getByText("当前角色为只读访问")).toBeVisible();

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByRole("heading", { name: "待审批操作", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("等待有权限的审批人处理"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批并执行" }),
  ).toHaveCount(0);

  await page.goto("/customer-service/incidents");
  await expect(
    page.getByRole("heading", { name: "执行异常", exact: true }).last(),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "关闭事故" }),
  ).toHaveCount(0);

  await page.goto("/operations");
  await expect(
    page.getByRole("button", { name: "检查并恢复演示数据" }),
  ).toHaveCount(0);
});

test("审计员不看到任何写操作入口", async ({ page }) => {
  await useIdentity(page, "auditor");
  await mockPendingApproval(page);
  await page.goto("/");

  await expect(page).toHaveURL(/\/operations$/);
  await expect(navItem(page, "内部工单 / HR")).toBeVisible();
  await expect(navItem(page, "运行与审计")).toBeVisible();
  await expect(navItem(page, "电商运营复用")).toHaveCount(0);
  await expect(navItem(page, "企业服务台 Agent")).toHaveCount(0);

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByText("等待有权限的审批人处理"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "审批并执行" }),
  ).toHaveCount(0);

  await page.goto("/tickets");
  await expect(
    page.getByRole("button", { name: "创建演示工单" }),
  ).toHaveCount(0);
});

test("平台管理员看到完整菜单、重置入口和全部写操作", async ({ page }) => {
  await useIdentity(page, "platform-admin");
  await mockPendingApproval(page);
  await page.goto("/");

  await expect(page).toHaveURL(/\/overview$/);
  await expect(navItem(page, "平台总览")).toBeVisible();
  await expect(navItem(page, "员工、Skill 与 MCP")).toBeVisible();
  await expect(navItem(page, "模型与连接")).toBeVisible();
  await expect(navItem(page, "运行与审计")).toBeVisible();

  await page.goto("/customer-service/approvals");
  await expect(
    page.getByRole("button", { name: "审批并执行" }),
  ).toBeVisible();

  await page.goto("/ecommerce/products");
  await expect(page.getByRole("button", { name: "新增商品" })).toBeVisible();

  await page.goto("/operations");
  await expect(
    page.getByRole("button", { name: "检查并恢复演示数据" }),
  ).toBeVisible();
});

test("未知角色只得到 requester 能力，不出现管理员菜单", async ({ page }) => {
  await page.route("**/api/v1/me**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        actor_id: "oidc.unknown",
        role: "requester",
        role_label: "需求方",
        issuer: "https://idp.example.test",
        auth_mode: "oidc",
        service_identity: false,
        policy_version: "2026-10-27",
        test_identity_switch_enabled: false,
        business_units: ["bu_demo"],
        business_unit_labels: { bu_demo: "演示租户（固定数据）" },
        primary_business_unit_id: "bu_demo",
        active_business_unit_id: "bu_demo",
        capabilities: ["tickets.view_self"],
        features: {
          demo_reset: {
            enabled: false,
            business_unit_id: "bu_demo",
            active_business_unit_eligible: true,
            reason: "role_not_permitted",
          },
        },
      }),
    }),
  );

  await page.goto("/");

  await expect(page).toHaveURL(/\/tickets$/);
  await expect(navItem(page, "内部工单 / HR")).toBeVisible();
  await expect(navItem(page, "平台总览")).toHaveCount(0);
  await expect(navItem(page, "员工、Skill 与 MCP")).toHaveCount(0);
  await expect(navItem(page, "运行与审计")).toHaveCount(0);
  await expect(navItem(page, "企业服务台 Agent")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "创建演示工单" }),
  ).toHaveCount(0);
});
