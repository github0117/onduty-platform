import { expect, test } from "@playwright/test";

test("员工模型配置保存按钮提交 model_profile", async ({ page }) => {
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "PATCH" &&
      /\/api\/v1\/digital-employees\/[^/]+$/.test(
        new URL(item.url()).pathname,
      ),
  );
  await page.route("**/api/v1/digital-employees/*", async (route) => {
    if (route.request().method() !== "PATCH") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto("/models/employees");
  await page.getByRole("button", { name: "配置模型" }).first().click();
  await expect(
    page.getByText(/配置模型 ·/).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "保存当前员工配置" })
    .click();
  const request = await requestPromise;
  expect(request.postDataJSON()).toMatchObject({
    model_profile: expect.objectContaining({
      generation: expect.any(Object),
      classification: expect.any(Object),
      claim_verifier: expect.any(Object),
      rerank: expect.any(Object),
    }),
  });
});
