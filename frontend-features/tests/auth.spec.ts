import { expect, test } from "./fixtures"

test("an anonymous visitor is sent to sign in, then back to where they were going", async ({
  page,
  clinic,
}) => {
  await page.goto("/scripts")
  await expect(page).toHaveURL(/\/login\?redirect=%2Fscripts/)
  await page.getByLabel("Email").fill(clinic.email)
  await page.getByLabel("Password").fill(clinic.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL(/\/scripts$/)
  await expect(
    page.getByRole("heading", { name: "Script staging queue" }),
  ).toBeVisible()
})

test("a wrong password is refused without saying which half was wrong", async ({
  page,
  clinic,
}) => {
  await page.goto("/login")
  await page.getByLabel("Email").fill(clinic.email)
  await page.getByLabel("Password").fill("not-the-password")
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page.getByRole("alert")).toHaveText(
    "That email and password don't match an active account.",
  )
  await expect(page).toHaveURL(/\/login/)
})

test("an off-site redirect target is ignored", async ({
  page,
  clinic,
  baseURL,
}) => {
  await page.goto("/login?redirect=//evil.example/phish")
  await page.getByLabel("Email").fill(clinic.email)
  await page.getByLabel("Password").fill(clinic.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  // The app's own home page, on whatever origin it is served from (PLAYWRIGHT_BASE_URL).
  await expect(page).toHaveURL(new URL("/", baseURL).href)
})

// Signs in through the UI: the `signedIn` fixture re-seeds its token on every navigation.
test("signing out clears the session", async ({ page, clinic }) => {
  await page.goto("/login")
  await page.getByLabel("Email").fill(clinic.email)
  await page.getByLabel("Password").fill(clinic.password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(
    page.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "Sign out" }).click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto("/patients")
  await expect(page).toHaveURL(/\/login/)
})
