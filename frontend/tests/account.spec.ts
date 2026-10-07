import { randomBytes } from "node:crypto"
import type { APIRequestContext } from "@playwright/test"
import { expect, test } from "./fixtures"

/**
 * The signed-out account flows: organisation signup, password recovery and reset.
 *
 * Budget note: `POST /password-recovery/{email}` and `POST /reset-password/` share one 5/min window
 * per client address (`backend/app/core/rate_limit.py`), and sign-in is 20/min. This file spends 4
 * recovery calls and 2 sign-ins against one backend per run (CI gives every shard its own backend);
 * keep it that way, or the suite starts failing on `429` instead of on behaviour. The recovery tests
 * are never retried: a retry would spend the same window again and fail on `429`, hiding the real
 * failure, and CI fails a run on any flaky test (`--fail-on-flaky-tests`), so a retry could never
 * rescue it anyway. Running the whole file twice inside a minute against one backend will also hit
 * the limit; that is the control working, not a defect.
 */

const MAILPIT = process.env.MAILPIT_HOST ?? "http://localhost:8025"

const run = () => randomBytes(4).toString("hex")
const newEmail = (prefix: string) => `${prefix}-${run()}@e2e.example.com`
const newPassword = () => `E2e-${randomBytes(9).toString("base64url")}`

/** The newest email Mailpit caught for `to`, as HTML. Polls: delivery is asynchronous. */
const waitForEmailHtml = async (request: APIRequestContext, to: string) => {
  let html: string | undefined
  await expect
    .poll(
      async () => {
        const search = await request.get(`${MAILPIT}/api/v1/search`, {
          params: { query: `to:"${to}"`, limit: 1 },
        })
        if (!search.ok()) return false
        const { messages } = (await search.json()) as {
          messages: { ID: string }[]
        }
        if (!messages[0]) return false
        const view = await request.get(`${MAILPIT}/view/${messages[0].ID}.html`)
        html = await view.text()
        return view.ok()
      },
      { timeout: 10_000, message: `no email reached ${to}` },
    )
    .toBe(true)
  return html!
}

test.describe("organisation signup", () => {
  test("registering a clinic creates the organisation and signs its owner in", async ({
    page,
  }) => {
    await page.goto("/login")
    await page.getByRole("link", { name: "Create an organisation" }).click()
    await expect(page).toHaveURL(/\/signup$/)
    await expect(
      page.getByRole("heading", { name: "Register your clinic" }),
    ).toBeVisible()

    const password = newPassword()
    await page.getByLabel("Clinic or practice name").fill(`Wattle GP ${run()}`)
    await page.getByLabel("Your full name").fill("Dr Lena Moss")
    await page.getByLabel("Email").fill(newEmail("signup"))
    await page.getByLabel("Password", { exact: true }).fill(password)
    await page.getByLabel("Confirm password").fill(password)
    await page.getByRole("button", { name: "Register clinic" }).click()

    // The new owner lands in their own, empty clinic, signed in.
    await expect(
      page.getByRole("heading", { name: "Today's clinic" }),
    ).toBeVisible()
    await expect(page.getByText("Dr Lena Moss", { exact: true })).toBeVisible()
  })

  test("every field is checked before anything is sent", async ({ page }) => {
    let calls = 0
    await page.route("**/api/v1/users/signup", (route) => {
      calls += 1
      return route.continue()
    })
    await page.goto("/signup")
    await page.getByRole("button", { name: "Register clinic" }).click()
    await expect(
      page.getByText("Enter your clinic or practice name."),
    ).toBeVisible()
    await expect(page.getByText("Enter your full name.")).toBeVisible()
    await expect(page.getByText("Enter a valid email address.")).toBeVisible()
    await expect(page.getByText("Choose a password.")).toBeVisible()
    await expect(page.getByLabel("Clinic or practice name")).toBeFocused()

    await page.getByLabel("Clinic or practice name").fill("Wattle GP")
    await page.getByLabel("Your full name").fill("Dr Lena Moss")
    await page.getByLabel("Email").fill(newEmail("signup"))
    await page.getByLabel("Password", { exact: true }).fill("short")
    await page.getByRole("button", { name: "Register clinic" }).click()
    await expect(page.getByText("Use at least 8 characters.")).toBeVisible()

    await page.getByLabel("Password", { exact: true }).fill("long-enough-1")
    await page.getByLabel("Confirm password").fill("long-enough-2")
    await page.getByRole("button", { name: "Register clinic" }).click()
    await expect(page.getByText("The passwords don't match.")).toBeVisible()
    expect(calls).toBe(0)
  })

  test("an email that already has an account is refused at the email field", async ({
    page,
    clinic,
  }) => {
    const password = newPassword()
    await page.goto("/signup")
    await page.getByLabel("Clinic or practice name").fill("Another clinic")
    await page.getByLabel("Your full name").fill("Someone Else")
    await page.getByLabel("Email").fill(clinic.email)
    await page.getByLabel("Password", { exact: true }).fill(password)
    await page.getByLabel("Confirm password").fill(password)
    await page.getByRole("button", { name: "Register clinic" }).click()
    await expect(
      page.getByText("An account already uses this email. Sign in instead."),
    ).toBeVisible()
    await expect(page.getByLabel("Email")).toHaveAttribute(
      "aria-invalid",
      "true",
    )
    await expect(page).toHaveURL(/\/signup$/)
  })

  test("a server failure is explained, with its reference, and nothing moves", async ({
    page,
  }) => {
    await page.route("**/api/v1/users/signup", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/problem+json",
        body: JSON.stringify({
          type: "about:blank",
          title: "Service Unavailable",
          status: 503,
          detail: "Service Unavailable",
          request_id: "e2e0000000000000000000000000beef",
        }),
      }),
    )
    const password = newPassword()
    await page.goto("/signup")
    await page.getByLabel("Clinic or practice name").fill("Wattle GP")
    await page.getByLabel("Your full name").fill("Dr Lena Moss")
    await page.getByLabel("Email").fill(newEmail("signup"))
    await page.getByLabel("Password", { exact: true }).fill(password)
    await page.getByLabel("Confirm password").fill(password)
    await page.getByRole("button", { name: "Register clinic" }).click()
    const alert = page.getByRole("alert")
    await expect(alert).toContainText("Something went wrong on our side.")
    await expect(alert).toContainText(
      "Reference e2e0000000000000000000000000beef",
    )
    await expect(page).toHaveURL(/\/signup$/)
  })

  test("a signed-in person is sent to the app, not the signup form", async ({
    signedIn: page,
  }) => {
    await page.goto("/signup")
    await expect(
      page.getByRole("heading", { name: "Today's clinic" }),
    ).toBeVisible()
    await page.goto("/recover-password")
    await expect(
      page.getByRole("heading", { name: "Today's clinic" }),
    ).toBeVisible()
  })
})

test.describe("password recovery", () => {
  test.describe.configure({ retries: 0 })

  test("the emailed link sets a new password that then signs in", async ({
    page,
    request,
  }) => {
    const email = newEmail("recover")
    const signup = await request.post("/api/v1/users/signup", {
      data: {
        email,
        password: newPassword(),
        full_name: "Dr Ana Ruiz",
        clinic_name: `Recovery clinic ${run()}`,
      },
    })
    expect(signup.ok(), await signup.text()).toBeTruthy()

    await page.goto("/login")
    await page.getByRole("link", { name: "Forgot password?" }).click()
    await expect(page).toHaveURL(/\/recover-password$/)
    // The URL changes before the code-split page renders; wait for it, not for the sign-in form.
    await expect(
      page.getByRole("heading", { name: "Reset your password" }),
    ).toBeVisible()
    await page.getByLabel("Email").fill(email)
    await page.getByRole("button", { name: "Send reset link" }).click()
    await expect(
      page.getByRole("heading", { name: "Check your email" }),
    ).toBeVisible()
    await expect(page.getByRole("status")).toContainText(email)

    // The backend builds `{FRONTEND_HOST}/reset-password?token=...`; follow its path here so the
    // test holds wherever FRONTEND_HOST points.
    const html = await waitForEmailHtml(request, email)
    const link = html.match(/\/reset-password\?token=[^"'<\s]+/)?.[0]
    expect(link, "reset link in the email").toBeTruthy()
    await page.goto(link!.replace(/&amp;/g, "&"))

    const fresh = newPassword()
    await page.getByLabel("New password", { exact: true }).fill(fresh)
    await page.getByLabel("Confirm new password").fill(fresh)
    await page.getByRole("button", { name: "Set new password" }).click()
    await expect(
      page.getByRole("heading", { name: "Password updated" }),
    ).toBeVisible()

    await page.getByRole("link", { name: "Sign in" }).click()
    await expect(page).toHaveURL(/\/login$/)
    await page.getByLabel("Email").fill(email)
    await page.getByLabel("Password").fill(fresh)
    await page.getByRole("button", { name: "Sign in" }).click()
    await expect(
      page.getByRole("heading", { name: "Today's clinic" }),
    ).toBeVisible()
    await expect(page.getByText("Dr Ana Ruiz", { exact: true })).toBeVisible()
  })

  test("an unknown email gets the same answer as a registered one", async ({
    page,
  }) => {
    const email = newEmail("nobody")
    await page.goto("/recover-password")
    await page.getByLabel("Email").fill(email)
    await page.getByRole("button", { name: "Send reset link" }).click()
    await expect(
      page.getByRole("heading", { name: "Check your email" }),
    ).toBeVisible()
    await expect(page.getByRole("status")).toHaveText(
      `If ${email} has a Clinic OS account, we've sent it a password reset link. It can take a minute to arrive; check your spam folder too.`,
    )
  })

  test("an invalid email is caught before anything is sent", async ({
    page,
  }) => {
    await page.goto("/recover-password")
    await page.getByLabel("Email").fill("not-an-email")
    await page.getByRole("button", { name: "Send reset link" }).click()
    await expect(
      page.getByText("Enter the email you sign in with."),
    ).toBeVisible()
    await page.getByRole("link", { name: "Back to sign in" }).click()
    await expect(page).toHaveURL(/\/login$/)
  })

  test("a link without a token explains itself and offers a new one", async ({
    page,
  }) => {
    await page.goto("/reset-password")
    await expect(
      page.getByRole("heading", { name: "This link is incomplete" }),
    ).toBeVisible()
    await page.getByRole("link", { name: "Send a new link" }).click()
    await expect(page).toHaveURL(/\/recover-password$/)
  })

  test("an invalid or expired token is refused and offers a new link", async ({
    page,
  }) => {
    await page.goto("/reset-password?token=not-a-real-token")
    const password = newPassword()
    await page.getByLabel("New password", { exact: true }).fill(password)
    await page.getByLabel("Confirm new password").fill("something-else-1")
    await page.getByRole("button", { name: "Set new password" }).click()
    await expect(page.getByText("The passwords don't match.")).toBeVisible()

    await page.getByLabel("Confirm new password").fill(password)
    await page.getByRole("button", { name: "Set new password" }).click()
    const alert = page.getByRole("alert")
    await expect(alert).toContainText(
      "This reset link has expired or isn't valid any more.",
    )
    await alert.getByRole("link", { name: "Send a new link" }).click()
    await expect(page).toHaveURL(/\/recover-password$/)
  })
})
