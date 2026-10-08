import { randomInt } from "node:crypto"
import { mkdirSync } from "node:fs"
import type {
  APIRequestContext,
  Locator,
  Page,
  TestInfo,
} from "@playwright/test"
import { signInWithApi, signUp } from "./accounts"
import { type Clinic, expect, openSignedIn, readClinic, test } from "./fixtures"

/**
 * Every screen at every supported width (docs2/design-system.md, Layout): the page never scrolls
 * sideways, the screen's heading and primary action are on it, and on a touch-sized screen (below
 * 1024 px) every control is at least a 44 px target. A full-page screenshot of each screen at each
 * width goes to `test-results/layout/<width>/<screen>.png` (CI uploads that folder) and to the report.
 *
 * Budget: each screen is loaded once and then resized through the widths, so the spec asks the API
 * about as often as one visit to each screen. That matters: the administrative routes allow 20
 * requests a minute per account (`backend/app/core/rate_limit.py`) and every signed-in spec shares
 * the setup project's owner. No test here signs in: the signed-in pages reuse the setup project's
 * token, and the public pages run signed out.
 */
const VIEWPORTS = [
  { width: 360, height: 780 },
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
] as const
type Viewport = (typeof VIEWPORTS)[number]

/** Below this width the sidebar is a drawer and the screen is treated as touch-sized. */
const DRAWER_BELOW = 1024
const TOUCH_TARGET = 44

const api = (request: APIRequestContext, token: string) => ({
  get: async <T>(path: string) => {
    const res = await request.get(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
    return (await res.json()) as T
  },
  post: (path: string, data: unknown) =>
    request.post(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      data,
    }),
})

const sydneyToday = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Sydney" })
const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
/** A name the patient schema accepts (letters only), different on every attempt. */
const letters = (n: number) =>
  Array.from({ length: n }, () => String.fromCharCode(97 + randomInt(26))).join(
    "",
  )

/** Sydney's UTC offset at `hh`:00 on `day`, as `+11:00` or `+10:00`. */
function sydneyOffset(day: string, hh: string): string {
  const name = new Intl.DateTimeFormat("en-AU", {
    timeZone: "Australia/Sydney",
    timeZoneName: "longOffset",
  })
    .formatToParts(new Date(`${day}T${hh}:00:00Z`))
    .find((p) => p.type === "timeZoneName")?.value
  return (name ?? "GMT+10:00").replace("GMT", "")
}

/**
 * A patient of this attempt's own with something on every screen: a booking today, a verified
 * approval and a covered draft script, so the Today page, the calendar, the register, the queue and
 * every tab of the record have rows to lay out.
 */
async function seedPatient(request: APIRequestContext, clinic: Clinic) {
  const owner = api(request, clinic.token)
  const verifier = api(request, clinic.verifier.token)
  const me = await owner.get<{ id: string }>("/users/me")
  const today = sydneyToday()
  const family = `Layout${letters(6)}`
  const created = await owner.post("/patients", {
    given_name: "Nell",
    family_name: family,
    date_of_birth: "1982-07-14",
    sex_at_birth: "FEMALE",
    state: "NSW",
    suburb: "Katoomba",
    phone: "0412 345 678",
  })
  expect(created.status(), await created.text()).toBe(201)
  const patient = ((await created.json()) as { id: string }).id

  // A booking today in clinic hours, moving on past any time another spec already took.
  for (let slot = randomInt(0, 24), booked = false; !booked; slot++) {
    expect(slot, "a free slot today").toBeLessThan(40)
    const minutes = 9 * 60 + slot * 15
    const hh = String(Math.floor(minutes / 60)).padStart(2, "0")
    const mm = String(minutes % 60).padStart(2, "0")
    const res = await owner.post("/appointments", {
      patient_id: patient,
      practitioner_id: me.id,
      type: "FOLLOW_UP",
      starts_at: new Date(
        `${today}T${hh}:${mm}:00${sydneyOffset(today, hh)}`,
      ).toISOString(),
    })
    if (res.status() === 201) booked = true
    else expect(res.status(), await res.text()).toBe(409)
  }

  const grain = { tga_category: "CATEGORY_2", dosage_form: "ORAL_LIQUID" }
  const reference = `SAS-B 2026-${letters(6).toUpperCase()}`
  const recorded = await owner.post("/tga-approvals", {
    patient_id: patient,
    ...grain,
    approval_reference: reference,
    creation_reason: "NEW_APPLICATION",
    valid_from: addDays(today, -30),
    valid_to: addDays(today, 365),
  })
  expect(recorded.status(), await recorded.text()).toBe(201)
  const approval = (await recorded.json()) as { id: string }
  const verified = await verifier.post(`/tga-approvals/${approval.id}/verify`, {
    tga_application_number: reference,
  })
  expect(verified.ok(), await verified.text()).toBeTruthy()

  const product = `Layout Check Oil ${letters(4)}`
  const staged = await owner.post("/prescriptions", {
    patient_id: patient,
    prescriber_id: me.id,
    medicine_name: product,
    ...grain,
    dose_instruction: "0.5 mL twice daily, titrate to effect",
    quantity: "1",
    repeats: 2,
    triage_outcome: "Eligible - chronic pain",
    conventional_therapy: "NSAIDs and physiotherapy, 9 months",
    date_of_service: today,
  })
  expect(staged.status(), await staged.text()).toBe(201)
  return { patient, product, name: `Nell ${family}` }
}

/**
 * Every visible control smaller than a touch target. Inline links inside running text are exempt
 * (WCAG 2.5.8's inline exception), as is anything inside `[data-touch-exempt]`, which marks a
 * pointer shortcut whose full-size equivalent is on the same screen.
 */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate((min) => {
    const selector = [
      "button",
      "a[href]",
      "[role=tab]",
      "[role=option]",
      "select",
      "textarea",
      "input:not([type=hidden])",
    ].join(",")
    const out: string[] = []
    for (const el of document.querySelectorAll<HTMLElement>(selector)) {
      if (el.closest("[data-touch-exempt], [aria-hidden=true], [inert]"))
        continue
      const style = getComputedStyle(el)
      if (style.visibility === "hidden" || style.display === "none") continue
      if (el.tagName === "A" && style.display === "inline") continue
      // A checkbox or radio is tapped through its label too, so the target is the larger of the
      // control and its labels (a visually hidden radio is measured by its label alone).
      const toggle =
        ["checkbox", "radio"].includes(el.getAttribute("type") ?? "") ||
        ["checkbox", "radio"].includes(el.getAttribute("role") ?? "")
      const labels = toggle ? [...((el as HTMLInputElement).labels ?? [])] : []
      const boxes = [el, ...labels].map((e) => e.getBoundingClientRect())
      const box = {
        width: Math.max(...boxes.map((b) => b.width)),
        height: Math.max(...boxes.map((b) => b.height)),
      }
      if (box.width <= 1 || box.height <= 1) continue
      // Half a pixel of slack for sub-pixel layout (a 44 px button can measure 43.99).
      if (box.height < min - 0.5 || box.width < min - 0.5) {
        const name = (
          el.getAttribute("aria-label") ||
          el.textContent ||
          el.getAttribute("name") ||
          el.id ||
          el.tagName
        )
          .trim()
          .replace(/\s+/g, " ")
          .slice(0, 40)
        out.push(
          `${el.tagName.toLowerCase()} "${name}" ${Math.round(box.width)}x${Math.round(box.height)}`,
        )
      }
    }
    return out
  }, TOUCH_TARGET)
}

/** A dialog sits inside the viewport, every edge on screen; its body scrolls instead. */
async function expectWithinViewport(
  dialog: Locator,
  viewport: Viewport,
  what: string,
) {
  const box = await dialog.boundingBox()
  expect(box, what).not.toBeNull()
  expect.soft(box!.x, `${what}: left edge`).toBeGreaterThanOrEqual(0)
  expect.soft(box!.y, `${what}: top edge`).toBeGreaterThanOrEqual(0)
  expect
    .soft(box!.x + box!.width, `${what}: right edge`)
    .toBeLessThanOrEqual(viewport.width)
  expect
    .soft(box!.y + box!.height, `${what}: bottom edge`)
    .toBeLessThanOrEqual(viewport.height)
  // The sticky header and footer never cover the body's content: scrolled to the top, the header
  // ends where the content starts; scrolled to the end, the footer starts where it ends.
  const overlap = await dialog.evaluate((d) => {
    const body = d.querySelector<HTMLElement>("[data-slot=dialog-body]")
    const header = d.querySelector("[data-slot=dialog-header]")
    const footer = d.querySelector("[data-slot=dialog-footer]")
    const covers = (top?: Element | null, bottom?: Element | null) =>
      top && bottom
        ? top.getBoundingClientRect().bottom -
          bottom.getBoundingClientRect().top
        : 0
    if (!body) return { header: 0, footer: 0 }
    const scrolled = body.scrollTop
    body.scrollTop = 0
    const headerOverlap = covers(header, header?.nextElementSibling)
    body.scrollTop = body.scrollHeight
    const footerOverlap = covers(footer?.previousElementSibling, footer)
    body.scrollTop = scrolled
    return { header: headerOverlap, footer: footerOverlap }
  })
  expect
    .soft(overlap.header, `${what}: header covers the body`)
    .toBeLessThanOrEqual(0.5)
  expect
    .soft(overlap.footer, `${what}: footer covers the body`)
    .toBeLessThanOrEqual(0.5)
}

/**
 * Checks what is on `page` at every width: the screen's heading and primary action are visible, the
 * page never scrolls sideways, touch-sized screens have no small targets, and a full-page
 * screenshot is saved. `dialog`, when the screen is a dialog, must also fit inside the viewport.
 */
async function checkEveryWidth(
  page: Page,
  testInfo: TestInfo,
  screen: string,
  ready: Locator[],
  dialog?: Locator,
) {
  for (const viewport of VIEWPORTS) {
    const at = `${screen} at ${viewport.width}px`
    await page.setViewportSize(viewport)
    for (const locator of ready) await expect(locator, at).toBeVisible()
    // Laid out with its data, not its loading skeletons.
    await expect(page.locator("[aria-busy=true]"), at).toHaveCount(0)
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect
      .soft(scrollWidth, `${at}: no sideways page scroll`)
      .toBeLessThanOrEqual(innerWidth)
    if (dialog) await expectWithinViewport(dialog, viewport, at)
    if (viewport.width < DRAWER_BELOW)
      expect.soft(await smallTargets(page), `${at}: touch targets`).toEqual([])

    const dir = `test-results/layout/${viewport.width}`
    mkdirSync(dir, { recursive: true })
    const path = `${dir}/${screen}.png`
    await page.screenshot({ path, fullPage: true, animations: "disabled" })
    await testInfo.attach(`${viewport.width}px ${screen}`, {
      path,
      contentType: "image/png",
    })
  }
  // Every screen loads at the narrowest width, the case most likely to break.
  await page.setViewportSize(VIEWPORTS[0])
}

const h1 = (page: Page, name: string | RegExp) =>
  page.getByRole("heading", { name, level: 1 })
const button = (page: Page, name: string | RegExp) =>
  page.getByRole("button", { name, exact: typeof name === "string" })

test.use({ viewport: VIEWPORTS[0] })

test("the public screens fit every width", async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const { slug } = readClinic()
  const screens: Array<[string, string, (p: Page) => Locator[]]> = [
    ["login", "/login", (p) => [h1(p, "Clinic OS"), button(p, "Sign in")]],
    [
      "signup",
      "/signup",
      (p) => [h1(p, "Register your clinic"), button(p, "Register clinic")],
    ],
    [
      "recover-password",
      "/recover-password",
      (p) => [h1(p, "Reset your password"), button(p, "Send reset link")],
    ],
    [
      "reset-password",
      "/reset-password?token=layout-check",
      (p) => [h1(p, "Choose a new password"), button(p, "Set new password")],
    ],
    [
      "accept-invite",
      "/accept-invite?token=layout-check",
      (p) => [h1(p, "Join your clinic"), button(p, "Set password and sign in")],
    ],
    [
      "book",
      `/book/${slug}`,
      (p) => [h1(p, "What kind of visit?"), button(p, "Continue")],
    ],
  ]
  for (const [name, path, ready] of screens) {
    await page.goto(path)
    await checkEveryWidth(page, testInfo, name, ready(page))
  }
  await button(page, "Continue").click()
  await checkEveryWidth(page, testInfo, "book-details", [
    h1(page, "A little about you"),
    button(page, "Choose a time"),
  ])
})

test("the care screens fit every width", async ({
  signedIn: page,
  clinic,
  request,
}, testInfo) => {
  test.setTimeout(180_000)
  const seeded = await seedPatient(request, clinic)

  await page.goto("/")
  await checkEveryWidth(page, testInfo, "today", [
    h1(page, "Today's clinic"),
    page.getByRole("region", { name: "Today's schedule" }),
  ])
  for (const view of ["day", "week"] as const) {
    await page.goto(`/calendar?view=${view}`)
    await checkEveryWidth(page, testInfo, `calendar-${view}`, [
      h1(page, "Calendar"),
      button(page, "New appointment"),
      page.getByRole("button", { name: new RegExp(seeded.name) }),
    ])
  }
  await page.goto("/patients")
  await checkEveryWidth(page, testInfo, "patients", [
    h1(page, "Patients"),
    button(page, "Add patient"),
  ])

  const tabs = [
    ["overview", "Edit details"],
    ["notes", "Save note"],
    ["approvals", "Record approval"],
    ["scripts", "Stage a script"],
    ["appointments", null],
    ["activity", null],
  ] as const
  for (const [tab, action] of tabs) {
    await page.goto(`/patients/${seeded.patient}?tab=${tab}`)
    await checkEveryWidth(page, testInfo, `patient-${tab}`, [
      h1(page, seeded.name),
      page.getByRole("tab", { selected: true }),
      action ? button(page, action) : page.getByRole("table"),
    ])
  }
})

test("the prescribing screens fit every width", async ({
  signedIn: page,
  clinic,
  request,
}, testInfo) => {
  test.setTimeout(120_000)
  const seeded = await seedPatient(request, clinic)

  await page.goto("/approvals?filter=all")
  await checkEveryWidth(page, testInfo, "approvals", [
    h1(page, "TGA approvals register"),
    button(page, "Record approval"),
  ])

  await page.goto("/scripts")
  const card = page.locator("article", { hasText: seeded.product })
  await checkEveryWidth(page, testInfo, "scripts", [
    h1(page, "Script staging queue"),
    button(page, "Stage a draft"),
    card.getByRole("button", { name: "Review & sign" }),
  ])

  // The sign dialog with its step-up password: header, body and footer all inside the viewport.
  await card.getByRole("button", { name: "Review & sign" }).click()
  const review = page.getByRole("dialog", { name: "Review & sign" })
  // It opens on the password field, in full view at phone height, not under the sticky footer.
  const password = review.getByLabel("Your password, to sign")
  await expect(password).toBeFocused()
  await expect
    .poll(() =>
      review.evaluate((d) => {
        const field = document.activeElement?.getBoundingClientRect()
        const footer = d
          .querySelector("[data-slot=dialog-footer]")
          ?.getBoundingClientRect()
        return field && footer ? footer.top - field.bottom : -1
      }),
    )
    .toBeGreaterThanOrEqual(0)
  await checkEveryWidth(
    page,
    testInfo,
    "scripts-sign-dialog",
    [
      review.getByRole("heading", { name: "Review & sign" }),
      review.getByLabel("Your password, to sign"),
      review.getByRole("button", { name: "Sign & queue for pharmacy" }),
    ],
    review,
  )
})

test("administration and settings fit every width", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(120_000)
  // An owner of its own: the administration routes allow 20 requests a minute per session, and the
  // admin and staff specs spend the shared owner's budget in the same minute (CI shard 3 saw 429s on
  // `/users/staff` and `/permissions`). One signup and one sign-in, inside both limits.
  const owner = await signUp(request, { clinic: true })
  await openSignedIn(page, await signInWithApi(request, owner), "/admin")
  await checkEveryWidth(page, testInfo, "admin-staff", [
    h1(page, "Administration"),
    button(page, "Invite staff member"),
    page.getByTestId("staff-table"),
  ])

  await button(page, "Invite staff member").click()
  const invite = page.getByRole("dialog", { name: "Invite a staff member" })
  await checkEveryWidth(
    page,
    testInfo,
    "admin-invite-dialog",
    [
      invite.getByRole("heading", { name: "Invite a staff member" }),
      invite.getByLabel("Full name"),
      invite.getByRole("button", { name: "Send invitation" }),
    ],
    invite,
  )
  await page.keyboard.press("Escape")
  await expect(invite).toBeHidden()

  await page.getByRole("tab", { name: "Roles and permissions" }).click()
  await checkEveryWidth(page, testInfo, "admin-roles", [
    h1(page, "Administration"),
    page.getByTestId("permission-matrix"),
  ])
  await page.getByRole("tab", { name: "User access" }).click()
  await checkEveryWidth(page, testInfo, "admin-access", [
    h1(page, "Administration"),
    page.getByRole("region", { name: "Assigned roles" }),
  ])

  for (const [tab, action] of [
    ["profile", "Save profile"],
    ["password", "Change password"],
    ["account", "Deactivate account"],
  ] as const) {
    await page.goto(`/settings?tab=${tab}`)
    await checkEveryWidth(page, testInfo, `settings-${tab}`, [
      h1(page, "Settings"),
      button(page, action),
    ])
  }
})

test("below 1024px the sidebar is a drawer that holds focus and closes on Escape", async ({
  signedIn: page,
}, testInfo) => {
  await page.goto("/")
  await expect(h1(page, "Today's clinic")).toBeVisible()
  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport)
    const menu = page.getByRole("button", { name: "Open navigation" })
    const sidebar = page.getByRole("navigation", { name: "Main" })
    if (viewport.width >= DRAWER_BELOW) {
      await expect(menu).toBeHidden()
      await expect(sidebar).toBeVisible()
      continue
    }
    await expect(sidebar).toBeHidden()
    await menu.click()
    const drawer = page.getByRole("dialog", { name: "Navigation" })
    await expect(drawer.getByRole("link", { name: "Patients" })).toBeVisible()
    expect
      .soft(await smallTargets(page), `drawer at ${viewport.width}px`)
      .toEqual([])
    const path = `test-results/layout/${viewport.width}/drawer.png`
    await page.screenshot({ path, animations: "disabled" })
    await testInfo.attach(`${viewport.width}px drawer`, {
      path,
      contentType: "image/png",
    })

    // Tab and Shift+Tab cycle inside the drawer; nothing behind it takes focus.
    for (const key of ["Tab", "Shift+Tab"])
      for (let i = 0; i < 30; i++) {
        await page.keyboard.press(key)
        expect(
          await drawer.evaluate((d) => d.contains(document.activeElement)),
          `${key} stays in the drawer`,
        ).toBe(true)
      }
    await page.keyboard.press("Escape")
    await expect(drawer).toBeHidden()
    await expect(menu).toBeFocused()

    // Following a link closes the drawer on the new page.
    await menu.click()
    await drawer.getByRole("link", { name: "Patients" }).click()
    await expect(drawer).toBeHidden()
    await expect(h1(page, "Patients")).toBeVisible()
    await page.goBack()
    await expect(h1(page, "Today's clinic")).toBeVisible()
  }
})
