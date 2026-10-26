import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= fileURLToPath(
  new URL("../../.cache/ms-playwright", import.meta.url),
);

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: {
    timeout: 20_000,
  },
  fullyParallel: false,
  // The suite shares one seeded demo database and asynchronous AI turns.
  // Parallel files create conversation bursts that exceed the model latency
  // budget, so run them one at a time.
  workers: 1,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
