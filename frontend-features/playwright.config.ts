import { defineConfig, devices } from "@playwright/test"

/**
 * End-to-end tests run the real app against a real backend.
 *
 * The dev server proxies `/api` to VITE_API_PROXY_TARGET (default http://127.0.0.1:8000), so start
 * the backend first (`docker compose watch`, or `fastapi dev` in backend/). The setup project signs
 * up a brand-new clinic through the API for each run, so runs never share data.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174"

export default defineConfig({
  testDir: "./tests",
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
