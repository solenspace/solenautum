import { defineConfig } from "@playwright/test";

// Run cadence: not on every PR (slow). Nightly cron + on-demand via
// `pnpm e2e`. The PR gate is the unit suite (`pnpm test`). Requires
// `DATABASE_URL`, Clerk keys, an LLM provider key, and
// `AUTUMN_URL_ALLOWLIST=127.0.0.1` in the api's env so the SSRF guard
// admits the fixture server on `:9999`.
export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  globalSetup: "./tests/e2e/global-setup.ts",
  use: {
    baseURL: process.env.AUTUMN_E2E_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "pnpm dev",
      port: 3000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "cd ../api && uv run uvicorn app.main:app --port 8000 --host 127.0.0.1",
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
