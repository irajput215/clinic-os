import { randomBytes } from "node:crypto"
import { expect, test } from "./fixtures"

/**
 * The patient record (docs3 feature 04; Platform Manual §3.2, §3.4): masked identifiers, the
 * eScript-ready chip, alerts, and the lifecycle status. The patient is archived at the end, so the
 * shared clinic's default patient list is what other specs expect.
 */
test("identifiers are masked, alerts show on the header and a status leaves the list", async ({
  signedIn: page,
  request,
  clinic,
}) => {
  const family = `Record${randomBytes(3).toString("hex")}`
  const created = await request.post("/api/v1/patients", {
    headers: { authorization: `Bearer ${clinic.token}` },
    data: {
      given_name: "Rhea",
      family_name: family,
      date_of_birth: "1979-07-21",
      sex_at_birth: "FEMALE",
      address_line: "14 Vulture St",
      suburb: "West End",
      state: "QLD",
      postcode: "4101",
      medicare_number: "2123 45670 1",
      medicare_irn: 1,
      ihi: "8003 6012 3456 7890",
    },
  })
  expect(created.status(), await created.text()).toBe(201)
  const patient = await created.json()

  await page.goto(`/patients/${patient.id}`)
  await expect(
    page.getByRole("heading", { name: `Rhea ${family}` }),
  ).toBeVisible()
  await expect(page.getByText("eScript-ready").first()).toBeVisible()
  // Only the last three digits ever reach the browser.
  await expect(page.getByText("•••• 701")).toBeVisible()
  await expect(page.getByText("•••• 890")).toBeVisible()
  expect(await page.content()).not.toContain("2123456701")

  await page.getByRole("button", { name: "Add alert" }).click()
  const alertDialog = page.getByRole("dialog", { name: "Add an alert" })
  await alertDialog.getByLabel("Alert").fill("Interpreter needed")
  await alertDialog.getByLabel("Tone").selectOption("WARN")
  await alertDialog.getByRole("button", { name: "Add alert" }).click()
  await expect(
    page.getByRole("list", { name: "Alerts" }).getByText("Interpreter needed"),
  ).toBeVisible()

  await page.getByRole("button", { name: "Change status" }).click()
  const statusDialog = page.getByRole("dialog", { name: "Change status" })
  await statusDialog.getByLabel("Status").selectOption("ARCHIVED")
  const save = statusDialog.getByRole("button", { name: "Change status" })
  await expect(save).toBeDisabled()
  await statusDialog.getByLabel("Reason").fill("Moved interstate")
  await save.click()
  await expect(
    page.getByText("Archived", { exact: true }).first(),
  ).toBeVisible()

  // Archived records leave the default list but stay findable.
  await page.goto("/patients")
  await expect(page.getByRole("cell", { name: /Marcus Webb/ })).toBeVisible()
  await expect(
    page.getByRole("cell", { name: new RegExp(family) }),
  ).toBeHidden()
  await page.getByLabel("Show patients by status").selectOption("ARCHIVED")
  await expect(
    page.getByRole("cell", { name: new RegExp(family) }),
  ).toBeVisible()
})
