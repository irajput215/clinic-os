import { expect, test } from "./fixtures"

test("the patients list shows the clinic's patients from the API", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await expect(page.getByRole("cell", { name: "Marcus Webb" })).toBeVisible()
  await page.getByLabel("Filter patients").fill("caru")
  await expect(page.getByRole("cell", { name: "Dean Caruso" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "Marcus Webb" })).toBeHidden()
})

test("a patient is added through the API and opens on their record", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("button", { name: "Add patient" }).first().click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(dialog.getByText("Enter a given name.")).toBeVisible()

  await dialog.getByLabel("Given name").fill("Luke")
  await dialog.getByLabel("Family name").fill("Lawson")
  await dialog.getByLabel("Date of birth").fill("1988-05-14")
  await dialog.getByLabel("Postcode").fill("30")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(dialog.getByText("Use a 4-digit postcode.")).toBeVisible()

  await dialog.getByLabel("Postcode").fill("3066")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(page).toHaveURL(/\/patients\/[0-9a-f-]{36}$/)
  await expect(page.getByRole("heading", { name: "Luke Lawson" })).toBeVisible()

  // The create is in the real, hash-chained audit trail.
  await page.getByRole("tab", { name: "Activity" }).click()
  await expect(page.getByRole("cell", { name: "Patient create" })).toBeVisible()
})

test("an unknown patient id is a not-found page, not an error", async ({
  signedIn: page,
}) => {
  await page.goto("/patients/00000000-0000-4000-8000-000000000000")
  await expect(
    page.getByText("That patient record isn't available."),
  ).toBeVisible()
})
