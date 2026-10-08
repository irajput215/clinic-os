import type { Request } from "@playwright/test"
import { expect, test } from "./fixtures"

/**
 * The API calls a cold load of Today makes (docs2/architecture.md "Speed measures"): the page itself
 * is one call, `GET /dashboard/today`; the shell adds the session, its permission set, the clinic's
 * slug and the two sidebar counts. Each is asked once, and none waits for another that it does
 * not need: the session and the permission set start together (`routes/_app.tsx`).
 *
 * The owner holds `tenant:read`, so the slug is asked; it waits for the permission set by design
 * (`data/tenant.ts`: never ask what the server is certain to refuse).
 */
const EXPECTED = [
  "/api/v1/dashboard/today",
  "/api/v1/prescriptions?limit=100",
  "/api/v1/tenants/current",
  "/api/v1/tga-approvals?limit=1",
  "/api/v1/users/me",
  "/api/v1/users/me/permissions",
]

interface Call {
  path: string
  request: Request
}

/** Start and end of a finished request, in the browser's own clock (ms since the epoch). */
const span = (request: Request) => {
  const timing = request.timing()
  return { start: timing.startTime, end: timing.startTime + timing.responseEnd }
}

test("a cold load of Today asks each API question once, with no waterfall", async ({
  signedIn: page,
}) => {
  const calls: Call[] = []
  page.on("request", (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith("/api/"))
      calls.push({ path: url.pathname + url.search, request })
  })

  await page.goto("/")
  await expect(
    page.getByRole("heading", { level: 1, name: "Today's clinic" }),
  ).toBeVisible()
  // The slug is the last read (after the permission set); it labels the sidebar.
  await expect(page.getByTestId("sidebar-clinic")).not.toBeEmpty()
  await page.waitForLoadState("networkidle")

  expect(calls.map((c) => c.path).sort()).toEqual(EXPECTED)

  const finished = async (path: string) => {
    const call = calls.find((c) => c.path === path)
    expect(call, path).toBeDefined()
    expect((await call!.request.response())?.ok(), path).toBe(true)
    return span(call!.request)
  }
  const me = await finished("/api/v1/users/me")
  const permissions = await finished("/api/v1/users/me/permissions")
  const today = await finished("/api/v1/dashboard/today")
  const scripts = await finished("/api/v1/prescriptions?limit=100")
  const approvals = await finished("/api/v1/tga-approvals?limit=1")

  // Session and permissions are in flight together: each started before the other finished.
  expect(permissions.start).toBeLessThan(me.end)
  expect(me.start).toBeLessThan(permissions.end)
  // So are the page's own read and the sidebar's counts: nothing waits for `/users/me`.
  for (const other of [today, scripts, approvals])
    expect(other.start).toBeLessThan(me.end)
})
