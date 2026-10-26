import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

const apiHeaders = {
  "X-Actor-Id": "e2e-ecommerce",
  "X-Actor-Role": "admin",
  "X-Business-Unit-Id": "bu_demo",
};

async function pendingListing(
  request: APIRequestContext,
): Promise<{ id: string; version: number }> {
  const products = await request.get(
    "/api/v1/ecommerce/products?business_unit_id=bu_demo",
    { headers: apiHeaders },
  );
  expect(products.ok()).toBeTruthy();
  const product = (
    (await products.json()) as Array<{ id: string; sku: string }>
  ).find((item) => item.sku === "ECO-CUP-001");
  expect(product).toBeTruthy();

  const response = await request.post(
    "/api/v1/ecommerce/listing-tasks?business_unit_id=bu_demo",
    {
      headers: apiHeaders,
      data: {
        product_id: product!.id,
        channel: "local_shop",
        market_code: "CN",
      },
    },
  );
  expect(response.ok(), await response.text()).toBeTruthy();
  const listing = (await response.json()) as {
    id: string;
    version: number;
    status: string;
  };
  expect(listing.status).toBe("PENDING_REVIEW");
  return { id: listing.id, version: listing.version };
}

async function mockReview(
  page: Page,
  listingId: string,
  expectedDecision: "ACCEPTED" | "REJECTED",
) {
  const requestPromise = page.waitForRequest(
    (item) =>
      item.method() === "POST" &&
      item.url().endsWith(
        `/ecommerce/listing-tasks/${listingId}/reviews`,
      ),
  );
  await page.route(
    `**/api/v1/ecommerce/listing-tasks/${listingId}/reviews`,
    async (route) => {
      const body = route.request().postDataJSON() as {
        decision?: string;
      };
      expect(body.decision).toBe(expectedDecision);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: listingId,
          version: 2,
          status:
            expectedDecision === "ACCEPTED" ? "PUBLISHING" : "REJECTED",
          message: "reviewed",
        }),
      });
    },
  );
  return { requestPromise };
}

test("电商上架任务通过按钮提交 ACCEPTED", async ({ page, request }) => {
  const listing = await pendingListing(request);
  const { requestPromise } = await mockReview(
    page,
    listing.id,
    "ACCEPTED",
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto(`/ecommerce/listings?listing=${listing.id}`);
  await expect(
    page.getByRole("button", { name: "通过并发布" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "通过并发布" }).click();
  await requestPromise;
});

test("电商上架任务退回按钮提交 REJECTED", async ({ page, request }) => {
  const listing = await pendingListing(request);
  const { requestPromise } = await mockReview(
    page,
    listing.id,
    "REJECTED",
  );
  await page.addInitScript(() => window.localStorage.clear());
  await page.goto(`/ecommerce/listings?listing=${listing.id}`);
  await expect(
    page.getByRole("button", { name: /退\s*回/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: /退\s*回/ }).click();
  await requestPromise;
});
