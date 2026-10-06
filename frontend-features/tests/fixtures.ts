import { readFileSync } from "node:fs"
import { test as base, expect, type Page } from "@playwright/test"

export const CLINIC_FILE = "playwright/.auth/clinic.json"

export interface Clinic {
  email: string
  password: string
  fullName: string
}

export const readClinic = (): Clinic =>
  JSON.parse(readFileSync(CLINIC_FILE, "utf8")) as Clinic

/**
 * `signedIn` is a page that arrives signed in. The app keeps its token in sessionStorage, which
 * Playwright's storageState does not capture, so the token is seeded before the first document loads.
 *
 * One sign-in per worker, not per test: `POST /login/access-token` is rate limited (20/min), and a
 * suite that signs in per test trips it. Tokens live 15 minutes, far longer than a worker.
 */
export const test = base.extend<
  { clinic: Clinic; signedIn: Page },
  { workerToken: string }
>({
  workerToken: [
    async ({ playwright }, use, workerInfo) => {
      const clinic = readClinic()
      const api = await playwright.request.newContext({
        baseURL: workerInfo.project.use.baseURL,
      })
      const res = await api.post("/api/v1/login/access-token", {
        form: { username: clinic.email, password: clinic.password },
      })
      expect(res.ok(), `sign-in failed: ${res.status()}`).toBeTruthy()
      const { access_token } = await res.json()
      await api.dispose()
      await use(access_token as string)
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
