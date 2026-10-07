import { defineConfig, devices } from "@playwright/test"

/**
 * End-to-end tests run the real app against a real backend.
 *
 * With PLAYWRIGHT_BASE_URL set, the suite runs against that origin as it is, with no dev server:
 * CI points it at the backend container, which serves the production build of this app at `/` and
 * the API under `/api` (see .github/workflows/playwright.yml and compose.override.yml). Locally,
 * `PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 bun run test` does the same against a backend serving
 * `bun run build`.
 *
 * Without it, the Vite dev server is started and proxies `/api` to VITE_API_PROXY_TARGET (default
 * http://127.0.0.1:8000), so start the backend first (`docker compose watch`, or `fastapi dev` in
 * backend/). The setup project signs up a brand-new clinic through the API for each run, so runs
 * never share data.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174"

export default defineConfig({
  testDir: "./tests",
  globalTeardown: "./tests/global-teardown.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "blob" : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
    timezoneId: "Australia/Sydney",
    locale: "en-AU",
  },
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: "bun run dev",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
      },
})
