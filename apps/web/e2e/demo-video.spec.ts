import { expect, test, type Page } from "@playwright/test";

// Watchable demo material, not a CI regression. It drives the real seeded
// stack so the video shows actual routing, streaming, conflicts and evaluation.
const recording = process.env.RECORD_DEMO === "1";

const overlayCss = `
  #demo-brand {
    position: fixed;
    right: 26px;
    top: 22px;
    z-index: 2147483646;
    padding: 8px 14px;
    border-radius: 999px;
    color: rgba(255, 255, 255, 0.92);
    background: rgba(15, 23, 42, 0.78);
    border: 1px solid rgba(255, 255, 255, 0.18);
    font: 600 14px/1.2 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    letter-spacing: 0.02em;
    pointer-events: none;
    backdrop-filter: blur(8px);
  }
  #demo-caption {
    position: fixed;
    left: 50%;
    bottom: 30px;
    transform: translateX(-50%);
    z-index: 2147483646;
    max-width: 84vw;
    padding: 15px 30px;
    border-radius: 999px;
    color: #f8fafc;
    background: rgba(15, 23, 42, 0.92);
    border: 1px solid rgba(255, 255, 255, 0.16);
    box-shadow: 0 18px 50px rgba(15, 23, 42, 0.32);
    font: 600 20px/1.45 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    text-align: center;
    letter-spacing: 0.01em;
    pointer-events: none;
    backdrop-filter: blur(10px);
    opacity: 0;
  }
  #demo-caption.demo-caption-enter {
    animation: demo-caption-in 0.35s ease forwards;
  }
  @keyframes demo-caption-in {
    from { opacity: 0; transform: translate(-50%, 10px); }
    to { opacity: 1; transform: translate(-50%, 0); }
  }
  #demo-cursor {
    position: fixed;
    left: 50%;
    top: 50%;
    z-index: 2147483647;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 3px solid #ffffff;
    background: rgba(22, 119, 255, 0.92);
    box-shadow: 0 4px 16px rgba(22, 119, 255, 0.45);
    transform: translate(-50%, -50%);
    transition: left 0.09s linear, top 0.09s linear, transform 0.09s ease;
    pointer-events: none;
  }
  #demo-cursor.pressed {
    transform: translate(-50%, -50%) scale(1.45);
  }
  #demo-title-card {
    position: fixed;
    inset: 0;
    z-index: 2147483647;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 14px;
    background: radial-gradient(circle at 50% 40%, #1d4ed8 0%, #0f172a 62%);
    color: #ffffff;
    pointer-events: none;
    animation: demo-title-out 4.4s ease forwards;
  }
  #demo-title-card .demo-title-eyebrow {
    font: 600 15px/1.2 -apple-system, "PingFang SC", sans-serif;
    letter-spacing: 0.32em;
    color: rgba(191, 219, 254, 0.86);
  }
  #demo-title-card .demo-title-main {
    font: 700 54px/1.2 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    letter-spacing: 0.04em;
  }
  #demo-title-card .demo-title-sub {
    font: 400 22px/1.5 -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    color: rgba(226, 232, 240, 0.9);
  }
  @keyframes demo-title-out {
    0% { opacity: 0; }
    8% { opacity: 1; }
    82% { opacity: 1; }
    100% { opacity: 0; }
  }
`;

async function installOverlay(page: Page): Promise<void> {
  await page.evaluate((css: string) => {
    if (document.getElementById("demo-caption")) return;

    const style = document.createElement("style");
    style.id = "demo-overlay-style";
    style.textContent = css;
    document.head.appendChild(style);

    const brand = document.createElement("div");
    brand.id = "demo-brand";
    brand.textContent = "OnDuty 数字员工平台 · 演示";
    document.body.appendChild(brand);

    const caption = document.createElement("div");
    caption.id = "demo-caption";
    document.body.appendChild(caption);

    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    document.body.appendChild(cursor);
    cursor.style.left = `${window.innerWidth - 120}px`;
    cursor.style.top = `${window.innerHeight - 120}px`;

    window.addEventListener("mousemove", (event) => {
      cursor.style.left = `${event.clientX}px`;
      cursor.style.top = `${event.clientY}px`;
    });
    window.addEventListener("mousedown", () =>
      cursor.classList.add("pressed"),
    );
    window.addEventListener("mouseup", () =>
      cursor.classList.remove("pressed"),
    );
  }, overlayCss);
}

async function setCaption(page: Page, text: string): Promise<void> {
  await page.evaluate((value: string) => {
    const caption = document.getElementById("demo-caption");
    if (!caption) return;
    caption.textContent = value;
    caption.classList.remove("demo-caption-enter");
    void caption.offsetWidth;
    caption.classList.add("demo-caption-enter");
  }, text);
}

async function showTitleCard(page: Page): Promise<void> {
  await page.evaluate(() => {
    const card = document.createElement("div");
    card.id = "demo-title-card";
    card.innerHTML = `
      <div class="demo-title-eyebrow">DIGITAL WORKFORCE DEMO</div>
      <div class="demo-title-main">OnDuty 数字员工平台</div>
      <div class="demo-title-sub">一个入口 · 多名数字员工 · 可治理的路由与评测</div>
    `;
    document.body.appendChild(card);
    window.setTimeout(() => card.remove(), 4500);
  });
  await page.waitForTimeout(4600);
}

async function openDemoPage(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(1600);
  await installOverlay(page);
}

async function waitForAnswer(page: Page): Promise<void> {
  await page
    .locator(".chat-bubble-streaming")
    .waitFor({ state: "visible", timeout: 60_000 })
    .catch(() => undefined);
  await page.waitForTimeout(1200);
  await expect(page.locator(".chat-bubble-streaming")).toHaveCount(0, {
    timeout: 120_000,
  });
  await page.waitForTimeout(1400);
}

test("按员工分派 · 意图治理 · 路由评测", async ({ page }) => {
  test.skip(!recording, "set RECORD_DEMO=1 (or run pnpm demo:video)");

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

  await openDemoPage(page, "/customer-service?scenario=enterprise");
  await installOverlay(page);
  await showTitleCard(page);
  await setCaption(page, "01 · 一个企业服务台入口，按问题自动分派数字员工");
  await page.waitForTimeout(2600);

  await setCaption(
    page,
    "01 · 员工问入职材料，入口员工池自动选中 HR 数字员工",
  );
  await page.getByRole("button", { name: "入职材料", exact: true }).click();
  await waitForAnswer(page);

  const headerEmployee = page.locator(
    ".chat-window-header .employee-profile-link",
  );
  await expect(headerEmployee).toContainText("HR", { timeout: 60_000 });
  await page.waitForTimeout(1500);

  await setCaption(
    page,
    "01 · 点击员工姓名，查看本次处理员工的 Skill、知识与 MCP 快照",
  );
  await headerEmployee.click();
  await expect(page.locator(".ant-drawer-title")).toContainText("员工快照", {
    timeout: 20_000,
  });
  await page.waitForTimeout(1600);
  await page.locator(".ant-drawer-body").evaluate((element) =>
    element.scrollBy({ top: 520, behavior: "smooth" }),
  );
  await page.waitForTimeout(2600);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(900);

  await setCaption(
    page,
    "01 · 同一入口再问账号问题，改为分派企业服务台数字员工",
  );
  await page.getByRole("button", { name: "重新开始" }).click();
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "账号被锁", exact: true }).click();
  await waitForAnswer(page);
  await expect(headerEmployee).toContainText("企业服务台", {
    timeout: 60_000,
  });
  await page.waitForTimeout(1800);

  await openDemoPage(page, "/employees/routing");
  await setCaption(
    page,
    "02 · 业务入口绑定员工池，HR 员工同时复用于内部 HR 入口",
  );
  await expect(
    page.getByRole("heading", {
      name: "业务入口与员工路由",
      exact: true,
    }),
  ).toBeVisible();
  await page.waitForTimeout(3200);

  await page
    .getByText("意图归属冲突检查", { exact: true })
    .scrollIntoViewIfNeeded();
  await expect(page.getByText("继承意图已让位", { exact: true })).toBeVisible();
  await setCaption(
    page,
    "02 · 意图归属冲突：显式规则优先，继承来的同名意图自动让位",
  );
  await page.waitForTimeout(4200);

  await page.evaluate(() =>
    window.scrollTo({ top: 0, behavior: "smooth" }),
  );
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "打开路由评测" }).click();
  await expect(page).toHaveURL(/\/employees\/route-evaluation/);
  await page.waitForTimeout(1600);
  await installOverlay(page);
  await setCaption(
    page,
    "03 · 每名员工 12 条固定问题，共 36 条路由评测用例",
  );
  await expect(
    page.getByRole("heading", { name: "路由评测集", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("启用的问题", { exact: true })).toBeVisible();
  await expect(page.getByText("36", { exact: true }).first()).toBeVisible({
    timeout: 30_000,
  });
  await page.waitForTimeout(2800);

  await page
    .getByText("评测问题", { exact: true })
    .scrollIntoViewIfNeeded();
  await setCaption(
    page,
    "03 · 运行评测复用真实路由，但不写入最近派单记录",
  );
  await page.waitForTimeout(3600);

  await page.evaluate(() =>
    window.scrollTo({ top: 0, behavior: "smooth" }),
  );
  await page.waitForTimeout(1200);
  const runButton = page.getByRole("button", { name: "运行评测" });
  await expect(runButton).toBeEnabled({ timeout: 30_000 });
  await runButton.click();
  await expect(
    page.getByText("路由评测完成：准确率 100%"),
  ).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(1800);

  await setCaption(
    page,
    "04 · 准确率、判断方式和候选证据都能追溯到每一条问题",
  );
  await page
    .getByText("最近评测结果", { exact: true })
    .scrollIntoViewIfNeeded();
  await page.waitForTimeout(1400);
  const resultCard = page
    .locator(".ant-card")
    .filter({ hasText: "最近评测结果" })
    .first();
  const expand = resultCard.locator(".ant-table-row-expand-icon").first();
  if (await expand.count()) {
    await expand.click();
  }
  await page.waitForTimeout(3600);

  await setCaption(
    page,
    "同一入口自动分派 · 冲突可治理 · 评测可回归",
  );
  await page.waitForTimeout(3400);
});
