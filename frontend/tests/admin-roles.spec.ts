import { expect as baseExpect, type Page, test } from "@playwright/test"

import { RolesService, UsersService } from "../src/client"
import { client } from "../src/client/client.gen"
import { createUser, createUserWithClinic } from "./utils/publicApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser } from "./utils/user"

/**
 * The administration screen.
 *
 * Every test registers its own organisation, because the roles API resolves the tenant from
 * the session: an account with no organisation is refused `403` before the screen can show
 * anything. The `setup` project logs in as `FIRST_SUPERUSER` and is a pre-existing local
 * failure (its `.env` credentials do not match the running database), so these tests carry
 * their own storage state and run with `--no-deps`.
 *
 * The tests are deliberately call-frugal. The administrative API is rate limited at 20
 * requests a minute per client address (`backend/app/core/rate_limit.py`), and one load of
 * this screen spends three of them, so a long spec would exhaust the window on its own
 * setup. `staleTime` on the screen's queries keeps a tab switch from refetching.
 *
 * The refusal test uses the generated client for the demotion that has to happen "behind
 * the page's back": that is what makes a real `403 GRANT_EXCEEDS_ACTOR` reachable from the
 * UI, which is the point of the screen.
 */

const expect = baseExpect.configure({ timeout: 90_000 })

test.describe.configure({ timeout: 240_000 })

const randomSuffix = () => Math.random().toString(36).slice(2, 10)

async function registerClinicAndLogIn(page: Page) {
  const email = randomEmail()
  const password = randomPassword()
  await createUserWithClinic({
    email,
    password,
    clinicName: `Clinic ${randomSuffix()}`,
  })
  await logInUser(page, email, password)
  return { email, password }
}

/** Point the generated client at the signed-in browser session for the setup calls. */
async function authenticateApiAs(page: Page) {
  const token = await page.evaluate(() => localStorage.getItem("access_token"))
  client.setConfig({ auth: () => token ?? "" })
}

/** The seeded role id for a code, read once for the test's own tenant. */
async function roleIdFor(code: string): Promise<string> {
  const roles = (await RolesService.listRoles()).data.data
  const role = roles.find((candidate) => candidate.code === code)
  if (!role) throw new Error(`missing seeded role ${code}`)
  return role.id
}

test.describe("Administration", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.beforeEach(() => {
    // A previous test may have pointed the client at a browser session; the signup helpers
    // are public and need no credential.
    client.setConfig({ auth: () => "" })
  })

  test("lists roles and the catalogue, and an assignment and revocation reflect in the account", async ({
    page,
  }) => {
    await registerClinicAndLogIn(page)

    await page.goto("/admin")

    await expect(
      page.getByRole("heading", { name: "Administration", level: 1 }),
    ).toBeVisible()
    // An organisation account lands on the roles tab.
    await expect(page.getByTestId("roles-panel")).toBeVisible()
    await expect(page.getByTestId("role-PRACTICE_OWNER")).toBeVisible()
    await expect(page.getByTestId("role-DOCTOR")).toBeVisible()
    await expect(page.getByTestId("role-PHARMACY")).toBeVisible()
    // The Doctor bundle is readable in the card.
    await expect(
      page.getByTestId("role-DOCTOR").getByText("prescription:sign"),
    ).toBeVisible()
    // A Practice Owner holds every permission, so every role is grantable.
    await expect(
      page.getByTestId("role-PRACTICE_OWNER").getByTestId("grantable-badge"),
    ).toBeVisible()
    await expect(page.getByTestId("cannot-grant-badge")).toHaveCount(0)

    // The catalogue groups the same codes by what they govern.
    await page.getByRole("tab", { name: "Permission catalogue" }).click()
    await expect(page.getByTestId("permissions-panel")).toBeVisible()
    await expect(
      page.getByTestId("permission-group-prescriptions"),
    ).toBeVisible()
    await expect(
      page.getByText("Sign a prescription as the prescriber of record."),
    ).toBeVisible()

    // One account: the signed-in user, who starts as Practice Owner.
    await page.getByRole("tab", { name: "User access" }).click()
    await expect(page.getByTestId("user-access-panel")).toBeVisible()
    await expect(
      page
        .getByTestId("user-roles")
        .getByText("PRACTICE_OWNER", { exact: true }),
    ).toBeVisible()

    // Assign Doctor: a real POST, then the list shows it and the effective set grows.
    await page.getByTestId("assign-role-select").click()
    await page.getByRole("option", { name: /^DOCTOR/ }).click()
    await page.getByTestId("assign-role-submit").click()

    await expect(page.getByText("Role assigned")).toBeVisible()
    await expect(
      page.getByTestId("user-roles").getByText("DOCTOR", { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByTestId("effective-permissions").getByText("prescription:sign"),
    ).toBeVisible()

    // Revoke Doctor: a real DELETE, then the list no longer shows it.
    await page.getByTestId("revoke-role-DOCTOR").click()
    await page.getByTestId("confirm-revoke-role").click()

    await expect(page.getByText("Doctor revoked")).toBeVisible()
    await expect(
      page.getByTestId("user-roles").getByText("DOCTOR", { exact: true }),
    ).toHaveCount(0)
  })

  test("marks a role the actor cannot grant and surfaces the API's refusal", async ({
    page,
  }) => {
    await registerClinicAndLogIn(page)
    await authenticateApiAs(page)

    const me = (await UsersService.readUserMe()).data
    const administrator = await roleIdFor("ADMINISTRATOR")
    const practiceOwner = await roleIdFor("PRACTICE_OWNER")

    // Make the account an Administrator-only before the screen loads: it keeps
    // `users:manage` (so the screen works) but does not hold the clinical permissions a
    // Doctor role carries.
    await UsersService.assignRole({
      path: { user_id: me.id },
      body: { role_id: administrator },
    })
    await UsersService.revokeRole({
      path: { user_id: me.id, role_id: practiceOwner },
    })

    await page.goto("/admin")

    await expect(page.getByTestId("roles-panel")).toBeVisible()
    const doctor = page.getByTestId("role-DOCTOR")
    await expect(doctor.getByTestId("cannot-grant-badge")).toBeVisible()
    await expect(
      doctor.getByTestId("role-DOCTOR-grantability-reason"),
    ).toContainText("You can grant only roles whose permissions you hold")
    await expect(
      doctor.getByTestId("role-DOCTOR-grantability-reason"),
    ).toContainText("prescription:sign")
    // Administrator is the one role an Administrator can grant.
    await expect(
      page.getByTestId("role-ADMINISTRATOR").getByTestId("grantable-badge"),
    ).toBeVisible()

    await page.getByRole("tab", { name: "User access" }).click()
    await expect(page.getByTestId("user-access-panel")).toBeVisible()

    // Choosing the non-grantable role warns before the attempt.
    await page.getByTestId("assign-role-select").click()
    await page.getByRole("option", { name: /^DOCTOR/ }).click()
    await expect(page.getByTestId("assign-presubmit-warning")).toBeVisible()

    // And the API — the only decision point — refuses the grant.
    await page.getByTestId("assign-role-submit").click()

    const refused = page.getByTestId("assign-refused")
    await expect(refused).toBeVisible()
    await expect(refused).toContainText(
      "You can grant only roles whose permissions you hold",
    )
    await expect(refused).toContainText("prescription:sign")
    await expect(refused).not.toContainText("Request failed with status code")
  })

  test("renders a permission-denied state, not a blank screen, for an account with no organisation", async ({
    page,
  }) => {
    const email = randomEmail()
    const password = randomPassword()
    await createUser({ email, password })
    await logInUser(page, email, password)

    // The catalogue tab makes one request; the API refuses it `403`, and the screen shows
    // the state rather than clearing the session or rendering nothing.
    await page.goto("/admin?tab=permissions")

    await expect(page.getByTestId("admin-access-denied")).toBeVisible()
    await expect(page.getByText("You do not have permission")).toBeVisible()
    await expect(page.getByTestId("error-component")).toHaveCount(0)
  })
})
