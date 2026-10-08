import { randomBytes } from "node:crypto"
import { verifySignupByEmail } from "./accounts"
import { expect, test } from "./fixtures"
import { emailedPath, waitForEmailHtml } from "./mail"

/**
 * The signed-out account flows: organisation signup, password recovery and reset.
 *
 * Budget note: `POST /password-recovery/{email}` and `POST /reset-password/` share one 5/min window
 * per client address (`backend/app/core/rate_limit.py`), and sign-in is 20/min. This file spends 4
 * recovery calls, 1 sign-in, 3 signups and 4 signup verifications (each 20/min) against one
 * backend per run (CI gives every shard its own backend); keep it that way, or the suite starts
 * failing on `429` instead of on behaviour. The recovery tests
 * are never retried: a retry would spend the same window again and fail on `429`, hiding the real
 * failure, and CI fails a run on any flaky test (`--fail-on-flaky-tests`), so a retry could never
 * rescue it anyway. A run started straight after another against the same backend first waits out
 * the previous run's window (`pacing.ts`), so back-to-back runs stay inside it too.
 */

const run = () => randomBytes(4).toString("hex")
const newEmail = (prefix: string) => `${prefix}-${run()}@e2e.example.com`
const newPassword = () => `E2e-${randomBytes(9).toString("base64url")}`

test.describe("organisation signup", () => {
  test("registering a clinic emails a link that creates it and signs its owner in, once", async ({
    page,
    request,
    browser,
  }) => {
    await page.goto("/login")
    await page.getByRole("link", { name: "Create an organisation" }).click()
    await expect(page).toHaveURL(/\/signup$/)
    await expect(
      page.getByRole("heading", { name: "Register your clinic" }),
    ).toBeVisible()

    const password = newPassword()
    const email = newEmail("signup")
    await page.getByLabel("Clinic or practice name").fill(`Wattle GP ${run()}`)
    await page.getByLabel("Your full name").fill("Dr Lena Moss")
    await page.getByLabel("Email").fill(email)
    await page.getByLabel("Password", { exact: true }).fill(password)
    await page.getByLabel("Confirm password").fill(password)
    await page.getByRole("button", { name: "Register clinic" }).click()

    // Nothing exists yet: the page asks the person to open the emailed link.
    await expect(
      page.getByRole("heading", { name: "Check your email" }),
    ).toBeVisible()
    await expect(page.getByRole("status")).toContainText(email)

    // "Send the email again" mails a fresh link; the first one stops working.
    const first = emailedPath(
      await waitForEmailHtml(request, email),
      "/verify-email",
    )
    await page.getByRole("button", { name: "Send the email again" }).click()
    await expect(page.getByText("Sent again.")).toBeVisible()
    const link = emailedPath(
      await waitForEmailHtml(request, email, 2),
      "/verify-email",
    )
    expect(link).not.toBe(first)

    await page.goto(link)
    await page.getByRole("button", { name: "Confirm and sign in" }).click()

    // The new owner lands in their own, empty clinic, signed in.
    await expect(
      page.getByRole("heading", { name: "Today's clinic" }),
    ).toBeVisible()
    await expect(page.getByText("Dr Lena Moss", { exact: true })).toBeVisible()

    // The link is spent, and the one the resend replaced never worked again.
    for (const used of [link, first]) {
      const context = await browser.newContext()
      const other = await context.newPage()
      await other.goto(used)
      await other.getByRole("button", { name: "Confirm and sign in" }).click()
      await expect(other.getByRole("alert")).toContainText(
        "has already been used",
      )
      await expect(other.getByRole("link", { name: "Sign in" })).toBeVisible()
      await expect(
        other.getByRole("link", { name: "Register again" }),
      ).toBeVisible()
      await context.close()
    }
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

  test("an email that already has an account gets the same page, and its owner a notice", async ({
    page,
    clinic,
    request,
  }) => {
    const password = newPassword()
    await page.goto("/signup")
    await page.getByLabel("Clinic or practice name").fill("Another clinic")
    await page.getByLabel("Your full name").fill("Someone Else")
    await page.getByLabel("Email").fill(clinic.email)
    await page.getByLabel("Password", { exact: true }).fill(password)
    await page.getByLabel("Confirm password").fill(password)
    await page.getByRole("button", { name: "Register clinic" }).click()
    // Exactly what a new address sees: nothing says the address has an account.
    await expect(
      page.getByRole("heading", { name: "Check your email" }),
    ).toBeVisible()
    await expect(page.getByRole("status")).toContainText(clinic.email)
    await expect(page.getByText("already uses this email")).toHaveCount(0)

    // The owner of the address is told, and gets no link (the setup's verification email was the
    // first message to this address).
    const notice = await waitForEmailHtml(request, clinic.email, 2)
    expect(notice).toContain("You already have an account")
    expect(notice).not.toContain("/verify-email")
    expect(notice).not.toContain("Another clinic")

    // "Use a different email" goes back to the filled form to correct the address.
    await page.getByRole("button", { name: "Use a different email" }).click()
    await expect(page.getByLabel("Email")).toBeFocused()
    await expect(page.getByLabel("Clinic or practice name")).toHaveValue(
      "Another clinic",
    )
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
    expect(signup.status(), await signup.text()).toBe(202)
    await verifySignupByEmail(request, email)

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
    // The second email to this address: the first was the signup's verification link.
    const html = await waitForEmailHtml(request, email, 2)
    await page.goto(emailedPath(html, "/reset-password"))

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
