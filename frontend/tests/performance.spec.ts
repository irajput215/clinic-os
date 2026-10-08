import type { Page } from "@playwright/test"
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
