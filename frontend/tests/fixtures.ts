import { readFileSync } from "node:fs"
import { test as base, expect, type Page } from "@playwright/test"

export const CLINIC_FILE = "playwright/.auth/clinic.json"

export interface Clinic {
  email: string
  password: string
  fullName: string
  /** The organisation's routing slug, as the server derives it from the clinic name at signup. */
  slug: string
  /** The owner's access token, from the setup project's one sign-in. */
  token: string
  /**
   * The owner of a second clinic of its own, signed in once by the setup project. For the tests
   * that change their own account's name or roles, or view their own administration, so they never
   * touch the shared clinic and never spend a sign-in of their own.
   */
  peer: SignedInAccount
}

export interface SignedInAccount {
  email: string
  password: string
  fullName: string
  token: string
}

export const readClinic = (): Clinic =>
  JSON.parse(readFileSync(CLINIC_FILE, "utf8")) as Clinic

/**
 * `signedIn` is a page that arrives signed in. The app keeps its token in sessionStorage, which
 * Playwright's storageState does not capture, so the token is seeded before the first document loads.
 *
 * Sign-in budget: `POST /login/access-token` is limited to 20 a minute per client address
 * (`backend/app/core/rate_limit.py`), and every worker shares that address. So a session is a
 * token the setup project signed in for, never a fresh sign-in: the only sign-ins a run spends are
 * the setup project's, one per fresh account a test must own, and those whose subject is signing in
 * (the sign-in page, a changed or recovered password, a deactivated account, an accepted invitation,
 * the password re-entry that signs a script). One run spends 18 of the 20; adding one is a budget
 * decision, not a free step. The setup project also waits out the window a previous run against the same
 * backend may have left (`waitOutPreviousRun`), so back-to-back runs never meet a `429`.
 * Tokens live 15 minutes, longer than a run (CI bounds a shard at 13).
 */
export const test = base.extend<
  { clinic: Clinic; signedIn: Page },
  { workerToken: string }
>({
  workerToken: [
    // biome-ignore lint/correctness/noEmptyPattern: Playwright reads fixture dependencies from this pattern
    async ({}, use) => {
      await use(readClinic().token)
    },
    { scope: "worker" },
  ],
  // biome-ignore lint/correctness/noEmptyPattern: Playwright reads fixture dependencies from this pattern
  clinic: async ({}, use) => {
    await use(readClinic())
  },
  signedIn: async ({ page, workerToken }, use) => {
    await page.addInitScript((token) => {
      window.sessionStorage.setItem("clinic-os.access_token", token)
    }, workerToken)
    await use(page)
  },
})

export { expect }

/**
 * Open `to` signed in with `token`, seeded once rather than on every navigation (as `signedIn`
 * does), so a test can still sign out, or be signed out, and stay signed out.
 */
export async function openSignedIn(page: Page, token: string, to = "/") {
  await page.goto("/login")
  await page.evaluate((value) => {
    window.sessionStorage.setItem("clinic-os.access_token", value)
  }, token)
  await page.goto(to)
}
