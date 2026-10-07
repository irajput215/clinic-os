import { signInThroughUi, signInWithApi, signUp } from "./accounts"
import { expect, openSignedIn, test } from "./fixtures"

// Changing a password or a name must never touch the shared clinic: the name and phone tests use
// the setup project's second clinic (`clinic.peer`), and the tests that change a password or
// deactivate an account sign up an account of their own.

test("a person updates their own name, and the app shows it", async ({
  page,
  clinic,
}) => {
  await openSignedIn(page, clinic.peer.token)

  const nav = page.getByRole("navigation", { name: "Main" })
  await nav.getByRole("link", { name: "Settings" }).click()
  await expect(
    page.getByRole("heading", { name: "Settings", level: 1 }),
  ).toBeVisible()

  const save = page.getByRole("button", { name: "Save profile" })
  await expect(save).toBeDisabled()
  await page.getByLabel("Full name").fill("Dr Ana Petrović-Hale")
  await save.click()
  await expect(page.getByText("Profile saved")).toBeVisible()
  await expect(save).toBeDisabled()

  // The sidebar reads the same account, so it agrees without a reload, and after one.
  await expect(page.getByTitle("Your settings")).toContainText(
    "Dr Ana Petrović-Hale",
  )
  await page.reload()
  await expect(page.getByLabel("Full name")).toHaveValue("Dr Ana Petrović-Hale")
})

test("a person changes their password, then signs in with the new one", async ({
  page,
  request,
}) => {
  const me = await signUp(request, { clinic: true })
  await openSignedIn(page, await signInWithApi(request, me), "/settings")
  await page.getByRole("tab", { name: "Password" }).click()

  // A wrong current password is refused by the server, in its own words.
  await page.getByLabel("Current password").fill("not-my-password")
  await page.getByLabel("New password", { exact: true }).fill("Banksia-new-77")
  await page.getByLabel("Confirm new password").fill("Banksia-new-77")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByRole("alert")).toHaveText("Incorrect password")

  // Mismatched confirmation is caught before anything is sent.
  await page.getByLabel("Current password").fill(me.password)
  await page.getByLabel("Confirm new password").fill("Banksia-new-78")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByText("The passwords don't match.")).toBeVisible()

  await page.getByLabel("Confirm new password").fill("Banksia-new-77")
  await page.getByRole("button", { name: "Change password" }).click()
  await expect(page.getByText("Password changed")).toBeVisible()
  await expect(page.getByLabel("Current password")).toHaveValue("")

  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)

  // The old password no longer works; the new one does.
  await page.getByLabel("Email").fill(me.email)
  await page.getByLabel("Password").fill(me.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("alert")).toHaveText(
    "That email and password don't match an active account.",
  )
  await signInThroughUi(page, { email: me.email, password: "Banksia-new-77" })
  await expect(
    page.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible()
})

test("deactivating your own account asks first, then signs you out for good", async ({
  page,
  request,
}) => {
  const me = await signUp(request, { clinic: false })
  await openSignedIn(page, await signInWithApi(request, me), "/settings")
  await page.getByRole("tab", { name: "Account" }).click()

  await page.getByRole("button", { name: "Deactivate account" }).click()
  const confirm = page.getByRole("dialog", { name: "Deactivate your account?" })
  await confirm.getByRole("button", { name: "Keep my account" }).click()
  await expect(confirm).toBeHidden()
  await expect(page).toHaveURL(/\/settings/)

  await page.getByRole("button", { name: "Deactivate account" }).click()
  await confirm.getByRole("button", { name: "Deactivate" }).click()
  await expect(page).toHaveURL(/\/login/)

  await page.getByLabel("Email").fill(me.email)
  await page.getByLabel("Password").fill(me.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("alert")).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
})

test("settings and administration fit a phone screen without sideways scrolling", async ({
  page,
  clinic,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openSignedIn(page, clinic.peer.token, "/settings")
  for (const path of ["/settings", "/settings?tab=password", "/admin"]) {
    await page.goto(path)
    await expect(page.getByRole("tablist")).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow, path).toBeLessThanOrEqual(0)
  }
})
