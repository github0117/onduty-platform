import { expect, test, type APIRequestContext } from "@playwright/test";

const headers = {
  "X-Actor-Id": "e2e-real-repair",
  "X-Actor-Role": "admin",
  "X-Business-Unit-Id": "bu_demo",
};

async function responseJson<T>(
  response: Awaited<ReturnType<APIRequestContext["post"]>>,
): Promise<T> {
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as T;
}

test("真实测试数据完成知识失败修复发布和回归验证", async ({
  page,
  request,
}) => {
  const suffix = Date.now().toString(36);
  const query = "退款到账需要几个工作日";
  const caseName = `真实修复回归 ${suffix}`;
  const documentTitle = `验收退款知识 ${suffix}`;
  let spaceId = "";
  let documentId = "";
  let caseId = "";

  try {
    const space = await responseJson<{ id: string }>(
      await request.post("/api/v1/knowledge-spaces", {
        headers,
        data: {
          business_unit_id: "bu_demo",
          code: `e2e_repair_${suffix}`,
          name: `真实修复验收空间 ${suffix}`,
          description: "Playwright 真实闭环测试数据",
          domain: "e2e",
          owner_id: "e2e-real-repair",
          evaluation_required: false,
        },
      }),
    );
    spaceId = space.id;

    const document = await responseJson<{ id: string }>(
      await request.post("/api/v1/knowledge-documents", {
        headers,
        data: {
          space_id: spaceId,
          business_unit_id: "bu_demo",
          title: documentTitle,
          doc_type: "POLICY",
          owner_id: "e2e-real-repair",
          scope: {},
        },
      }),
    );
    documentId = document.id;

    const initialVersion = await responseJson<{ id: string }>(
      await request.post(
        `/api/v1/knowledge-documents/${documentId}/versions`,
        {
          headers,
          data: {
            version_label: "1.0",
            content:
              "这是一份会议安排、办公用品领取和请假流程说明，不包含售后时效。",
            effective_from: new Date().toISOString(),
          },
        },
      ),
    );
    await responseJson<Record<string, unknown>>(
      await request.post(
        `/api/v1/knowledge-documents/${documentId}/versions/${initialVersion.id}/publish`,
        {
          headers,
          data: { release_note: "真实修复验收初始版本" },
        },
      ),
    );

    const evaluationCase = await responseJson<{
      id: string;
      enabled: boolean;
    }>(
      await request.post("/api/v1/knowledge/evaluation-cases", {
        headers,
        data: {
          business_unit_id: "bu_demo",
          knowledge_space_id: spaceId,
          employee_id: null,
          name: caseName,
          query,
          expected_titles: [documentTitle],
          expect_no_grounding: false,
          scope: {},
        },
      }),
    );
    caseId = evaluationCase.id;
    expect(evaluationCase.enabled).toBe(true);
    await responseJson<Record<string, unknown>>(
      await request.patch(
        `/api/v1/knowledge/evaluation-cases/${caseId}`,
        {
          headers,
          data: { enabled: true },
        },
      ),
    );
    const listedCases = await request.get(
      "/api/v1/knowledge/evaluation-cases?business_unit_id=bu_demo",
      { headers },
    );
    expect(listedCases.ok(), await listedCases.text()).toBeTruthy();
    const listedCase = (
      (await listedCases.json()) as Array<{
        id: string;
        enabled: boolean;
        knowledge_space_id: string | null;
      }>
    ).find((item) => item.id === caseId);
    expect(listedCase).toMatchObject({
      enabled: true,
      knowledge_space_id: spaceId,
    });

    const failedRun = await responseJson<{ verdict: string }>(
      await request.post("/api/v1/knowledge/evaluation-runs", {
        headers,
        data: {
          business_unit_id: "bu_demo",
          knowledge_space_id: spaceId,
          top_k: 5,
          min_recall_at_k: 0.8,
          min_mrr: 0.6,
          min_no_grounding_accuracy: 0.8,
        },
      }),
    );
    expect(failedRun.verdict).toBe("FAIL");

    await page.addInitScript(() => window.localStorage.clear());
    await page.goto("/knowledge/repairs");
    const repairRow = page
      .locator("tr")
      .filter({ hasText: caseName })
      .first();
    await expect(repairRow).toBeVisible();
    await repairRow.getByRole("button", { name: "补充知识" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/knowledge/documents\\?space=${spaceId}$`),
    );
    await expect(
      page.getByText("正在查看指定知识空间的文档"),
    ).toBeVisible();

    await page
      .getByRole("button", { name: documentTitle, exact: true })
      .click();
    await page.getByRole("button", { name: "新建文本版本" }).click();
    const versionDialog = page.getByRole("dialog", {
      name: "新建文本知识版本",
    });
    await versionDialog.getByPlaceholder("版本号").fill("2.0");
    await versionDialog
      .getByPlaceholder("输入 SOP、FAQ 或制度正文")
      .fill(
        `# 退款到账说明\n\n问题：${query}\n\n标准答案：退款审核通过后通常需要 1 至 3 个工作日到账。`,
      );
    await versionDialog.getByRole("button").last().click();
    const draftVersionRow = page.locator("tr").filter({ hasText: "2.0" });
    await expect(draftVersionRow).toBeVisible();
    await draftVersionRow
      .getByRole("button", { name: /^发\s*布$/ })
      .click();
    await expect(page.getByText("知识版本已发布")).toBeVisible();

    await page.goto("/knowledge/repairs");
    const repairedRow = page
      .locator("tr")
      .filter({ hasText: caseName })
      .first();
    await repairedRow
      .getByRole("button", { name: "一键验证修复" })
      .click();
    await expect(
      page.getByText("验证通过，可以关闭修复任务"),
    ).toBeVisible({ timeout: 90_000 });
    await expect(
      repairedRow.getByText("验证通过", { exact: true }),
    ).toBeVisible();
    const closeButton = repairedRow.getByRole("button", {
      name: "关闭任务",
    });
    await expect(closeButton).toBeVisible();
    await closeButton.click();
    await expect(
      repairedRow.getByText("已关闭", { exact: true }),
    ).toBeVisible();
  } finally {
    if (caseId) {
      await request.patch(`/api/v1/knowledge/evaluation-cases/${caseId}`, {
        headers,
        data: { enabled: false },
      });
    }
    if (documentId) {
      await request.post(
        `/api/v1/knowledge-documents/${documentId}/archive`,
        { headers },
      );
    }
    if (spaceId) {
      await request.patch(`/api/v1/knowledge-spaces/${spaceId}`, {
        headers,
        data: { status: "DISABLED" },
      });
    }
    const repairs = await request.get(
      "/api/v1/knowledge/repair-tasks?business_unit_id=bu_demo",
      { headers },
    );
    if (repairs.ok()) {
      const payload = (await repairs.json()) as {
        items: Array<{
          id: string;
          title: string;
          query: string;
          status: string;
        }>;
      };
      for (const item of payload.items.filter(
        (task) =>
          task.query === query &&
          task.title.includes(caseName) &&
          task.status !== "CLOSED" &&
          Boolean(task.id),
      )) {
        await request.patch(`/api/v1/knowledge/repair-tasks/${item.id}`, {
          headers,
          data: { status: "CLOSED" },
        });
      }
    }
  }
});
