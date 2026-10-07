import { randomBytes } from "node:crypto"
import { signInThroughUi, signUp, superuser } from "./accounts"
import { expect, test } from "./fixtures"

/**
 * Administration, against the real API. The roles and access endpoints are the administrative
 * rate-limit class, 20 a minute per session (`backend/app/core/rate_limit.py`), and the tests that open
 * administration each do it as a different account, so no test spends another's budget and none
 * waits out a `429`. The sidebar's clinic read is the single-resource read class (300/min) and spends
 * none of it.
 */

test("a practice owner sees every role against the 21-permission catalogue", async ({
  signedIn: page,
}) => {
  await page.goto("/")
  const nav = page.getByRole("navigation", { name: "Main" })
  await nav.getByRole("link", { name: "Administration" }).click()

  await expect(
    page.getByRole("heading", { name: "Administration", level: 1 }),
  ).toBeVisible()
  // An organisation's administrator starts on its Staff; the matrix is one tab along.
  await expect(page.getByRole("tab", { name: "Staff" })).toHaveAttribute(
    "aria-selected",
    "true",
  )
  await page.getByRole("tab", { name: "Roles and permissions" }).click()
  await expect(
    page.getByRole("tab", { name: "Roles and permissions" }),
  ).toHaveAttribute("aria-selected", "true")
  // Accounts is the platform superuser's surface; an organisation's owner is not offered it.
  await expect(page.getByRole("tab", { name: "Accounts" })).toHaveCount(0)

  const matrix = page.getByTestId("permission-matrix")
  await expect(matrix).toBeVisible()
  await expect(matrix.locator("tbody tr[data-testid^='perm-']")).toHaveCount(21)
  await expect(matrix.getByRole("columnheader")).toContainText([
    "Permission",
    "Administrator",
    "Authorised Prescriber",
    "Compliance / Auditor",
    "Doctor",
    "Nurse",
    "Pharmacy",
    "Practice Owner",
  ])
  // A cell is a statement a screen reader can read, not a bare tick.
  const sign = matrix.getByTestId("perm-prescription:sign")
  await expect(
    sign.getByText("Doctor includes prescription:sign"),
  ).toBeAttached()
  await expect(
    sign.getByText("Pharmacy does not include prescription:sign"),
  ).toBeAttached()
  // The owner holds everything, so every role is grantable.
  await expect(matrix.getByTestId("grant-DOCTOR")).toHaveText("Yes")
  await expect(page.getByTestId("ungrantable-roles")).toHaveCount(0)
})

test("an owner grants and revokes a role, and cannot remove the last administrator", async ({
  page,
  request,
}) => {
  const owner = await signUp(request, { clinic: true })
  await signInThroughUi(page, owner, "/admin")
  await page.getByRole("tab", { name: "User access" }).click()

  const assigned = page.getByTestId("assigned-roles")
  await expect(assigned.getByText("Practice Owner")).toBeVisible()
  await expect(page.getByTestId("assigned-DOCTOR")).toHaveCount(0)

  await page
    .getByLabel("Role", { exact: true })
    .selectOption({ label: "Doctor" })
  await page.getByRole("button", { name: "Grant role" }).click()
  await expect(page.getByText("Doctor granted")).toBeVisible()
  await expect(page.getByTestId("assigned-DOCTOR")).toBeVisible()

  await page.getByRole("button", { name: "Revoke Doctor" }).click()
  const dialog = page.getByRole("dialog", { name: "Revoke Doctor?" })
  await dialog.getByRole("button", { name: "Revoke role" }).click()
  await expect(page.getByText("Doctor revoked")).toBeVisible()
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId("assigned-DOCTOR")).toHaveCount(0)

  // R8: the server refuses to leave the organisation with nobody who can manage users.
  await page.getByRole("button", { name: "Revoke Practice Owner" }).click()
  const last = page.getByRole("dialog", { name: "Revoke Practice Owner?" })
  await last.getByRole("button", { name: "Revoke role" }).click()
  await expect(last.getByRole("alert")).toContainText(
    "last account that can manage users",
  )
  await last.getByRole("button", { name: "Keep role" }).click()
  await expect(assigned.getByText("Practice Owner")).toBeVisible()
})

test("an account without the permission gets no Administration entry, and a refusal if it goes there", async ({
  page,
  request,
}) => {
  const staff = await signUp(request, { clinic: false })
  await signInThroughUi(page, staff)

  const nav = page.getByRole("navigation", { name: "Main" })
  await expect(nav.getByRole("link", { name: "Settings" })).toBeVisible()
  await expect(nav.getByRole("link", { name: "Administration" })).toHaveCount(0)
  // No organisation, so no clinic to name and no booking page to link: never a stand-in.
  await expect(page.getByTestId("sidebar-clinic")).toBeEmpty()
  await expect(nav.getByRole("link", { name: "Booking page" })).toHaveCount(0)

  await page.goto("/admin")
  await expect(
    page.getByRole("heading", { name: "Administration", level: 1 }),
  ).toBeVisible()
  await expect(page.getByText("Not available to your role.")).toBeVisible()
  await expect(page.getByTestId("permission-matrix")).toHaveCount(0)

  await page.goto("/admin?tab=access")
  await expect(page.getByText("Not available to your role.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Grant role" })).toHaveCount(0)
})

test("the platform superuser lists, adds, edits and deactivates accounts", async ({
  page,
}) => {
  const admin = superuser()
  await signInThroughUi(page, admin, "/admin")
  await expect(page.getByRole("tab", { name: "Accounts" })).toHaveAttribute(
    "aria-selected",
    "true",
  )
  const table = page.getByTestId("accounts-table")
  await expect(table).toBeVisible()

  const email = `added-${randomBytes(4).toString("hex")}@e2e.example.com`
  await page.getByRole("button", { name: "Add account" }).click()
  const add = page.getByRole("dialog", { name: "Add an account" })
  // Validation runs before anything is sent.
  await add.getByRole("button", { name: "Add account" }).click()
  await expect(add.getByText("Enter a valid email.")).toBeVisible()
  await add.getByLabel("Email").fill(email)
  await add.getByLabel("Full name").fill("Jordan Blake")
  await add.getByLabel("Password", { exact: true }).fill("Wattle-bark-42")
  await add.getByLabel("Confirm password").fill("Wattle-bark-42")
  await add.getByRole("button", { name: "Add account" }).click()
  await expect(page.getByText(`${email} added`)).toBeVisible()
  await expect(add).toBeHidden()

  // Newest first, so the new account is on the first page.
  const row = page.getByTestId(`account-${email}`)
  await expect(row).toContainText("Jordan Blake")
  await expect(row).toContainText("Active")

  await row.getByRole("button", { name: `Edit ${email}` }).click()
  const edit = page.getByRole("dialog", { name: "Edit account" })
  await edit.getByLabel("Full name").fill("Jordan Blake-Ng")
  await edit.getByRole("button", { name: "Save changes" }).click()
  await expect(page.getByText("Account saved")).toBeVisible()
  await expect(row).toContainText("Jordan Blake-Ng")

  await row.getByRole("button", { name: `Deactivate ${email}` }).click()
  const confirm = page.getByRole("dialog", { name: "Deactivate this account?" })
  await confirm.getByRole("button", { name: "Deactivate" }).click()
  await expect(page.getByText(`${email} deactivated`)).toBeVisible()
  await expect(row).toContainText("Inactive")

  // The signed-in account is marked as yours. It is the oldest account, so on a database that has
  // collected more than a page of accounts it is on a later page: page forward until it shows.
  // The confirmation must be fully dismissed first: until the modal unmounts after its close
  // animation, the page behind it is `aria-hidden` and the pager is absent from role queries.
  await expect(page.locator("[data-aria-hidden]")).toHaveCount(0)
  const self = page.getByTestId(`account-${admin.email}`)
  const next = page
    .getByRole("navigation", { name: "Accounts pages" })
    .getByRole("button", { name: "Next" })
  while (
    !(await self.isVisible()) &&
    (await next.count()) > 0 &&
    (await next.isEnabled())
  ) {
    const before = await table.textContent()
    await next.click()
    await expect(table).not.toHaveText(before ?? "")
  }
  await expect(self.getByText("You", { exact: true })).toBeVisible()
})
