import type { Page, Response } from "@playwright/test"
import { expect, test } from "./fixtures"

/**
 * Largest Contentful Paint budget for the two screens every session starts on: sign-in and Today
 * (docs2/architecture.md "Speed measures"). Each load is cold (a fresh browser context: no HTTP
 * cache, no query cache) and throttled through the Chrome DevTools Protocol to a clinic in
 * Australia on a fast mobile or ordinary office connection near a Sydney edge:
 *
 * - network "Fast 4G": 9 Mbit/s down, 1.5 Mbit/s up, 30 ms added round-trip latency;
 * - CPU slowed 2x, a mid-range laptop rather than a developer workstation.
 *
 * It measures the production build the backend serves, so it runs only with PLAYWRIGHT_BASE_URL
 * (CI and `PLAYWRIGHT_BASE_URL=... bun x playwright test`): the dev server ships unbundled modules
 * and would measure Vite, not the app. The two loads run one after the other, never alongside
 * each other.
 */
const LCP_BUDGET_MS = 2_000

const FAST_4G = {
  offline: false,
  latency: 30,
  downloadThroughput: (9 * 1_000_000) / 8,
  uploadThroughput: (1.5 * 1_000_000) / 8,
}
const CPU_SLOWDOWN = 2

test.describe.configure({ mode: "serial" })
test.skip(
  !process.env.PLAYWRIGHT_BASE_URL,
  "Measures the production build; the dev server serves unbundled modules",
)

async function throttle(page: Page) {
  const cdp = await page.context().newCDPSession(page)
  await cdp.send("Network.enable")
  await cdp.send("Network.emulateNetworkConditions", FAST_4G)
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU_SLOWDOWN })
  // Every entry the page reports, recorded from the first byte of the document.
  await page.addInitScript(() => {
    const w = window as typeof window & { __lcp?: number }
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) w.__lcp = entry.startTime
    }).observe({ type: "largest-contentful-paint", buffered: true })
  })
}

/** The page's final LCP, in ms from navigation start, once it has settled. */
async function largestContentfulPaint(page: Page): Promise<number> {
  await page.waitForLoadState("networkidle")
  await expect
    .poll(() =>
      page.evaluate(() => (window as typeof window & { __lcp?: number }).__lcp),
    )
    .toBeGreaterThan(0)
  const lcp = await page.evaluate(
    () => (window as typeof window & { __lcp?: number }).__lcp ?? 0,
  )
  test.info().annotations.push({
    type: "LCP",
    description: `${Math.round(lcp)} ms`,
  })
  return lcp
}

test("sign-in paints its largest content within budget", async ({ page }) => {
  await throttle(page)
  await page.goto("/login")
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible()

  expect(await largestContentfulPaint(page)).toBeLessThan(LCP_BUDGET_MS)
})

test("Today paints its largest content within budget", async ({
  signedIn: page,
}) => {
  await throttle(page)
  await page.goto("/")
  await expect(
    page.getByRole("heading", { level: 1, name: "Today's clinic" }),
  ).toBeVisible()

  expect(await largestContentfulPaint(page)).toBeLessThan(LCP_BUDGET_MS)
})

/**
 * Origin budgets, read from the app's own `Server-Timing` header (`app` = edge middleware to
 * response start, measured in the backend process): readiness under 50 ms, and each API call the
 * Today, patients, approvals, scripts and calendar screens make under 150 ms
 * (docs/reference/performance.md). Each screen is opened twice and the second, warm load counted,
 * so a process's first-request start-up is not mistaken for the steady state.
 */
const READY_BUDGET_MS = 50
const SCREEN_API_BUDGET_MS = 150
const SCREENS = ["/", "/patients", "/approvals", "/scripts", "/calendar"]
const SCREEN_APIS =
  /\/api\/v1\/(dashboard\/today|patients|tga-approvals|prescriptions|appointments)(\?|$)/

function appTiming(header: string | undefined): number | undefined {
  const match = header?.match(/(?:^|, )app;dur=([\d.]+)/)
  return match ? Number(match[1]) : undefined
}

test("readiness answers within its origin budget", async ({ request }) => {
  await request.get("/api/v1/health/ready/")
  const response = await request.get("/api/v1/health/ready/")
  expect(response.ok()).toBe(true)
  const app = appTiming(response.headers()["server-timing"])
  expect(app, "readiness sends Server-Timing").toBeDefined()
  expect(app).toBeLessThan(READY_BUDGET_MS)
})

test("every screen's API calls answer within the origin budget", async ({
  signedIn: page,
}) => {
  for (const screen of SCREENS) {
    await page.goto(screen)
    await page.waitForLoadState("networkidle")

    const timings: { url: string; app: number }[] = []
    const record = (response: Response) => {
      if (!SCREEN_APIS.test(`${new URL(response.url()).pathname}?`)) return
      const app = appTiming(response.headers()["server-timing"])
      if (app !== undefined) timings.push({ url: response.url(), app })
    }
    page.on("response", record)
    await page.reload()
    await page.waitForLoadState("networkidle")
    page.off("response", record)

    expect(
      timings.length,
      `${screen} made a measured API call`,
    ).toBeGreaterThan(0)
    for (const { url, app } of timings) {
      test.info().annotations.push({
        type: "Server-Timing app",
        description: `${new URL(url).pathname}: ${app} ms`,
      })
      expect(app, `${new URL(url).pathname} on ${screen}`).toBeLessThan(
        SCREEN_API_BUDGET_MS,
      )
    }
  }
})
