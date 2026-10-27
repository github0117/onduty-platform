import type { Page } from "@playwright/test";

export async function useIdentity(
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
