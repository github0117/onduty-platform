import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= fileURLToPath(
  new URL("../../.cache/ms-playwright", import.meta.url),
);

/**
 * Dedicated config for recording demo video material.
 *
 * Run against the seeded local stack:
 *   pnpm demo:video
 *
 * The scenario is skipped in the normal suite unless RECORD_DEMO=1.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "demo-video.spec.ts",
  timeout: 600_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "line",
  outputDir: "./demo-output",
  preserveOutput: "always",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 900 },
    video: { mode: "on", size: { width: 1440, height: 900 } },
    trace: "off",
    screenshot: "off",
  },
});
