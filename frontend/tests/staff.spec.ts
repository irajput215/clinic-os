import { randomBytes } from "node:crypto"
import type { APIResponse } from "@playwright/test"
import { expect, test } from "./fixtures"
import { emailedPath, waitForEmailHtml } from "./mail"

/**
 * Staff onboarding, against the real API and Mailpit: an administrator invites a person into their
 * own organisation, the person sets their own password from the emailed link and lands in that
 * organisation with the invited role.
 *
 * Budget: Staff, roles and access share the administrative 20-a-minute window per client address,
 * and the screen waits out a `429` (5 s, 20 s, 40 s), so steps that spend it allow for the wait.
 * Sign-in is 20 a minute for the whole suite, so the inviting side reuses the setup project's
 * owner session (`signedIn`, `clinic`) and the only sign-ins here are the two an accepted
 * invitation makes itself. Accepting has its own 5-a-minute window; this file spends three of it.
 * Retries would spend the windows again, so the file runs once.
 */
test.describe.configure({ timeout: 240_000, retries: 0 })
const slow = { timeout: 90_000 }

const run = () => randomBytes(4).toString("hex")
const newPassword = () => `E2e-${randomBytes(9).toString("base64url")}`

/**
 * An administrative API call made by the test itself, waiting out the shared 20-a-minute window
 * the way the screen does. The limit refuses before the request runs, so repeating it is safe.
 */
async function outlast429(send: () => Promise<APIResponse>) {
  for (let attempt = 0; ; attempt++) {
    const response = await send()
    if (response.status() !== 429 || attempt === 3) return response
    const wait = Number(response.headers()["retry-after"] ?? "5")
    await new Promise((resolve) => setTimeout(resolve, (wait + 1) * 1000))
  }
}

test("an owner invites a doctor, who sets a password once and lands in the clinic", async ({
  signedIn: page,
  clinic: owner,
  request,
  browser,
}) => {
  await page.goto("/admin")

  // Staff is where an organisation's administrator starts.
  await expect(page.getByRole("tab", { name: "Staff" })).toHaveAttribute(
    "aria-selected",
    "true",
  )
  const table = page.getByTestId("staff-table")
  await expect(table).toBeVisible(slow)
  await expect(table.getByTestId(`staff-${owner.email}`)).toContainText("You")
  await expect(table.getByTestId(`staff-${owner.email}`)).toContainText(
    "Practice Owner",
  )

  // Validation runs before anything is sent.
  await page.getByRole("button", { name: "Invite staff member" }).click()
  const dialog = page.getByRole("dialog", { name: "Invite a staff member" })
  await expect(dialog.getByTestId("invite-roles")).toBeVisible(slow)
  await dialog.getByRole("button", { name: "Send invitation" }).click()
  await expect(dialog.getByText("Enter the person's name.")).toBeVisible()
  await expect(dialog.getByText("Enter a valid email.")).toBeVisible()
  await expect(dialog.getByText("Choose at least one role.")).toBeVisible()

  const invitee = {
    email: `invitee-${run()}@e2e.example.com`,
    fullName: `Dr Mei Tanaka ${run()}`,
    password: newPassword(),
  }
  await dialog.getByLabel("Full name").fill(invitee.fullName)
  await dialog.getByLabel("Email").fill(invitee.email)
  // The owner holds every permission, so every role can be picked.
  await expect(dialog.getByLabel("Practice Owner")).toBeEnabled()
  await dialog.getByLabel("Doctor").check()
  await dialog.getByRole("button", { name: "Send invitation" }).click()
  await expect(
    page.getByText(`Invitation sent to ${invitee.email}`),
  ).toBeVisible(slow)
  await expect(dialog).toBeHidden()
  const row = table.getByTestId(`staff-${invitee.email}`)
  await expect(row).toContainText(invitee.fullName, slow)
  await expect(row).toContainText("Doctor")
  await expect(row).toContainText("Active")

  // The same address again is refused at the field, in words that name no organisation.
  await page.getByRole("button", { name: "Invite staff member" }).click()
  await dialog.getByLabel("Full name").fill("Someone Else")
  await dialog.getByLabel("Email").fill(invitee.email)
  await dialog.getByLabel("Nurse").check()
  await dialog.getByRole("button", { name: "Send invitation" }).click()
  await expect(dialog.getByText("can't be invited")).toBeVisible(slow)
  await dialog.getByRole("button", { name: "Cancel" }).click()

  // The person opens the emailed link in a browser of their own.
  const html = await waitForEmailHtml(request, invitee.email)
  expect(html).toContain(invitee.fullName)
  const link = emailedPath(html, "/accept-invite")
  const context = await browser.newContext()
  const theirs = await context.newPage()
  await theirs.goto(link)
  await expect(
    theirs.getByRole("heading", { name: "Join your clinic" }),
  ).toBeVisible()
  await theirs.getByRole("button", { name: "Set password and sign in" }).click()
  await expect(theirs.getByText("Choose a password.")).toBeVisible()
  await theirs.getByLabel("Password", { exact: true }).fill(invitee.password)
  await theirs.getByLabel("Confirm password").fill(invitee.password)
  await theirs.getByRole("button", { name: "Set password and sign in" }).click()

  // Signed in, in the owner's clinic, as a doctor: no Administration entry.
  await expect(
    theirs.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible(slow)
  await expect(
    theirs.getByRole("link", { name: invitee.fullName }),
  ).toBeVisible()
  // The session is in the owner's organisation (a doctor holds no `tenant:read`, so the sidebar
  // names no clinic; the account says which one it is).
  const tenantOf = async (token: string | null) =>
    (
      (await (
        await request.get("/api/v1/users/me", {
          headers: { Authorization: `Bearer ${token}` },
        })
      ).json()) as { tenant_id: string | null }
    ).tenant_id
  const theirToken = await theirs.evaluate(() =>
    window.sessionStorage.getItem("clinic-os.access_token"),
  )
  expect(await tenantOf(theirToken)).toBe(await tenantOf(owner.token))
  expect(await tenantOf(theirToken)).toBeTruthy()
  const nav = theirs.getByRole("navigation", { name: "Main" })
  await expect(nav.getByRole("link", { name: "Settings" })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Administration" })).toHaveCount(0)
  await context.close()

  // The link works once.
  const again = await browser.newContext()
  const replay = await again.newPage()
  await replay.goto(link)
  await replay.getByLabel("Password", { exact: true }).fill(newPassword())
  await replay.getByLabel("Confirm password").fill("mismatch-on-purpose")
  await replay.getByRole("button", { name: "Set password and sign in" }).click()
  await expect(replay.getByText("The passwords don't match.")).toBeVisible()
  const fresh = newPassword()
  await replay.getByLabel("Password", { exact: true }).fill(fresh)
  await replay.getByLabel("Confirm password").fill(fresh)
  await replay.getByRole("button", { name: "Set password and sign in" }).click()
  await expect(replay.getByRole("alert")).toContainText(
    "has expired or has already been used",
  )
  await expect(
    replay.getByRole("link", { name: "Get a new link" }),
  ).toBeVisible()
  await again.close()

  // Back in Administration: Manage access opens User access on the new account.
  await row
    .getByRole("button", { name: `Manage access for ${invitee.fullName}` })
    .click()
  await expect(page.getByRole("tab", { name: "User access" })).toHaveAttribute(
    "aria-selected",
    "true",
  )
  await expect(page.getByTestId("assigned-DOCTOR")).toBeVisible(slow)
  await expect(page.getByText(invitee.fullName, { exact: true })).toBeVisible()
})

test("an administrator can only offer the roles whose permissions they hold", async ({
  clinic,
  request,
  browser,
}) => {
  const auth = { Authorization: `Bearer ${clinic.token}` }
  const roles = await outlast429(() =>
    request.get("/api/v1/roles", { headers: auth }),
  )
  expect(roles.ok(), await roles.text()).toBeTruthy()
  const administrator = (
    (await roles.json()) as { data: { id: string; code: string }[] }
  ).data.find((role) => role.code === "ADMINISTRATOR")
  expect(administrator).toBeTruthy()

  const email = `admin-${run()}@e2e.example.com`
  const invited = await outlast429(() =>
    request.post("/api/v1/users/staff", {
      headers: auth,
      data: { email, full_name: "Priya Shah", role_ids: [administrator!.id] },
    }),
  )
  expect(invited.status(), await invited.text()).toBe(201)

  // The administrator accepts in a browser of their own and is signed straight in.
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(
    emailedPath(await waitForEmailHtml(request, email), "/accept-invite"),
  )
  const password = newPassword()
  await page.getByLabel("Password", { exact: true }).fill(password)
  await page.getByLabel("Confirm password").fill(password)
  await page.getByRole("button", { name: "Set password and sign in" }).click()
  await expect(
    page.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible(slow)

  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Administration" })
    .click()
  await expect(page.getByTestId("staff-table")).toBeVisible(slow)
  await page.getByRole("button", { name: "Invite staff member" }).click()
  const dialog = page.getByRole("dialog", { name: "Invite a staff member" })
  await expect(dialog.getByTestId("invite-roles")).toBeVisible(slow)
  await expect(dialog.getByLabel("Administrator")).toBeEnabled(slow)
  for (const name of ["Doctor", "Practice Owner", "Nurse"])
    await expect(dialog.getByLabel(name)).toBeDisabled()
  await expect(dialog.getByText("You can't grant this").first()).toBeVisible()
  await context.close()
})

test("staff and the invitation page fit a phone screen without sideways scrolling", async ({
  signedIn: page,
  browser,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/admin")
  await expect(page.getByTestId("staff-table")).toBeVisible(slow)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow, "/admin staff").toBeLessThanOrEqual(0)
  // The table fits its card too, rather than scrolling sideways inside it.
  const tableOverflow = await page
    .getByTestId("staff-table")
    .evaluate((t) => t.scrollWidth - (t.parentElement?.clientWidth ?? 0))
  expect(tableOverflow, "staff table").toBeLessThanOrEqual(0)

  await page.getByRole("button", { name: "Invite staff member" }).click()
  const dialog = page.getByRole("dialog", { name: "Invite a staff member" })
  await expect(dialog.getByTestId("invite-roles")).toBeVisible(slow)
  const box = await dialog.boundingBox()
  expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy()

  // Signed out (a browser of the invitee's own), the invitation page itself.
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  })
  const invitee = await context.newPage()
  await invitee.goto("/accept-invite?token=not-a-real-token")
  await expect(
    invitee.getByRole("heading", { name: "Join your clinic" }),
  ).toBeVisible()
  const acceptOverflow = await invitee.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(acceptOverflow, "/accept-invite").toBeLessThanOrEqual(0)
  await context.close()
})
