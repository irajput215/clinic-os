import { readFileSync } from "node:fs"
import { test as base, expect, type Page } from "@playwright/test"

export const CLINIC_FILE = "playwright/.auth/clinic.json"

export interface Clinic {
  email: string
  password: string
  fullName: string
  /** The owner's access token, from the setup project's one sign-in. */
  token: string
}

export const readClinic = (): Clinic =>
  JSON.parse(readFileSync(CLINIC_FILE, "utf8")) as Clinic

/**
 * `signedIn` is a page that arrives signed in. The app keeps its token in sessionStorage, which
 * Playwright's storageState does not capture, so the token is seeded before the first document loads.
 *
 * One sign-in per run, not per test or per worker: `POST /login/access-token` is rate limited
 * (20/min per client address), every worker shares that address, and the specs that sign in through
 * the UI on purpose spend most of the budget. The setup project signs in once and leaves the token
 * beside the clinic. Tokens live 15 minutes, longer than a run (CI bounds a shard at 13).
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
