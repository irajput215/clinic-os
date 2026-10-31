import { randomBytes } from "node:crypto"
import { expect, openSignedIn, test } from "./fixtures"

/**
 * Staff onboarding (docs3 feature 02). The setup project completes both doctors' onboarding packs
 * through the API, as an owner would, so every signing spec can sign; here the pack is read back, an
 * SOP is published and acknowledged, and the "first hour" card is shown and hidden.
 *
 * The SOP published here applies to everyone and is NOT required for onboarding: a required SOP
 * would un-complete both doctors' packs and stop the other specs signing.
 */

test("the staff list shows each doctor's pack, and the pack reads complete", async ({
  page,
  clinic,
}) => {
  await openSignedIn(page, clinic.token, "/admin?tab=staff")
  const row = page.getByTestId(`staff-${clinic.verifier.email}`)
  await expect(row.getByText("Pack complete").last()).toBeVisible()
  await row
    .getByRole("button", {
      name: `Onboarding pack for ${clinic.verifier.fullName}`,
    })
    .click()
  const pack = page.getByRole("dialog", { name: "Onboarding pack" })
  await expect(
    pack.getByText("Pack complete: ready to prescribe."),
  ).toBeVisible()
  await expect(pack.getByText("Signed version")).toBeVisible()
  // Values are masked by the server: only the last three characters ever reach the page.
  await expect(pack.getByText(/MED\d{10}/)).toHaveCount(0)
})

test("an SOP is published, acknowledged by a colleague, and shows on the matrix", async ({
  page,
  browser,
  clinic,
}) => {
  const title = `Hand hygiene ${randomBytes(3).toString("hex")}`
  await openSignedIn(page, clinic.token, "/sops")
  await page.getByRole("button", { name: "New SOP" }).click()
  const editor = page.getByRole("dialog")
  await editor.getByLabel("Title").fill(title)
  await editor
    .getByLabel("Procedure")
    .fill("Wash before and after every patient.")
  await editor.getByRole("button", { name: "Publish" }).click()
  await expect(page.getByText("Published version 1")).toBeVisible()

  const colleague = await browser.newPage()
  await openSignedIn(colleague, clinic.verifier.token, "/sops")
  const item = colleague.getByRole("button", { name: new RegExp(title) })
  await expect(item.getByText("Needs your acknowledgement")).toBeVisible()
  await item.click()
  await colleague.getByRole("button", { name: "Acknowledge version 1" }).click()
  await expect(colleague.getByText("You acknowledged v1")).toBeVisible()
  await colleague.keyboard.press("Escape")
  await expect(item.getByText("Acknowledged")).toBeVisible()
  await colleague.close()

  await page.goto("/sops?tab=matrix")
  const matrix = page.getByTestId("sop-matrix")
  await expect(
    matrix.getByRole("row", { name: new RegExp(clinic.verifier.fullName) }),
  ).toContainText("v1")
})

test("a doctor's first hour shows their checklist and stays hidden once dismissed", async ({
  page,
  clinic,
}) => {
  await openSignedIn(page, clinic.verifier.token, "/")
  const card = page.getByRole("region", { name: "Your first hour" })
  await expect(card.getByText("Script queue: Review & sign")).toBeVisible()
  await expect(card.getByText("You're ready to sign scripts.")).toBeVisible()
  await card.getByRole("button", { name: "Hide your first hour" }).click()
  await expect(card).toHaveCount(0)
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible()
  await expect(
    page.getByRole("region", { name: "Your first hour" }),
  ).toHaveCount(0)
})
