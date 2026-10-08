import { expect, test } from "./fixtures"

/**
 * The prescription safety gate, as the clinician meets it. Scripts are still preview (no
 * prescriptions module), so the script tests' gate decision comes from the preview store, which
 * mirrors the backend's match rules over sample approvals. The approval tests run against the real
 * tga_approvals API.
 */
test("a script with no covering approval cannot be signed", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("cell", { name: "Grace Liu" }).click()
  // Aurora is Category 3 capsules; nothing in this patient's approvals covers that grain.
  await page.getByRole("tab", { name: "Scripts" }).click()
  await page.getByRole("button", { name: "Stage a script" }).click()
  const stage = page.getByRole("dialog")
  await stage
    .getByLabel("Product")
    .selectOption({ label: "Aurora 10 Capsules" })
  await stage.getByLabel("Directions / titration").fill("1 capsule nocte")
  await stage.getByLabel("Triage outcome").fill("Eligible - insomnia")
  await stage
    .getByLabel("Conventional therapy first")
    .fill("Sleep hygiene, melatonin 6 months")
  await stage.getByRole("button", { name: "Stage draft" }).click()
  await expect(page.getByText("It can't be sent until one does.")).toBeVisible()

  const card = page.locator("article", { hasText: "Aurora 10 Capsules" })
  await card.getByRole("button", { name: "Review & sign" }).click()
  const review = page.getByRole("dialog")
  await expect(review.getByRole("status")).toContainText(
    "Safety gate: blocked.",
  )
  await expect(review.getByLabel("Your password, to sign")).toBeDisabled()
  await expect(
    review.getByRole("button", { name: "Sign & send to pharmacy" }),
  ).toBeDisabled()
})

// The approvals are the real API's (`tgaApprovals: "api"`); this one is recorded on the patient's
// own tab (the register is covered in approvals.spec.ts).
test("the person who records an approval cannot verify it", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("cell", { name: "Marcus Webb" }).click()
  await page.getByRole("tab", { name: "TGA approvals" }).click()
  await page.getByRole("button", { name: "Record approval" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("TGA category").selectOption("CATEGORY_2")
  await dialog.getByLabel("Dosage form").selectOption("OROMUCOSAL_SPRAY")
  await dialog.getByLabel("TGA reference").fill("SAS-B 2026-777001")
  await dialog.getByLabel("Valid to (as on the letter)").fill("2027-12-31")
  await dialog.getByRole("button", { name: "Record approval" }).click()
  await expect(dialog).toBeHidden()

  const row = page.getByRole("row", { name: /SAS-B 2026-777001/ })
  await expect(row).toContainText("Pending verification")
  await row.getByRole("button", { name: "Verify" }).click()
  const verify = page.getByRole("dialog")
  await verify
    .getByLabel("TGA reference from the letter")
    .fill("SAS-B 2026-777001")
  await verify.getByRole("button", { name: "Verify and activate" }).click()
  await expect(verify.getByRole("alert")).toHaveText(
    "You entered this approval, so a second clinician must verify it.",
  )
})

test("a covered script is signed with a password re-entry and sent", async ({
  signedIn: page,
  clinic,
}) => {
  await page.goto("/scripts")
  const card = page.locator("article", { hasText: "Covered through" }).first()
  const patient = (
    await card.locator("span.font-semibold").first().innerText()
  ).trim()
  await card.getByRole("button", { name: "Review & sign" }).click()
  const review = page.getByRole("dialog")
  await expect(review.getByRole("status")).toContainText("Safety gate: clear.")

  await review.getByLabel("Your password, to sign").fill("wrong-password")
  await review.getByRole("button", { name: "Sign & send to pharmacy" }).click()
  await expect(review.getByRole("alert")).toHaveText(
    "That password isn't right. Re-enter it to sign.",
  )

  await review.getByLabel("Your password, to sign").fill(clinic.password)
  await review.getByRole("button", { name: "Sign & send to pharmacy" }).click()
  await expect(page.getByText(/^Signed and sent to /)).toBeVisible()
  await expect(
    page
      .getByRole("row", {
        name: new RegExp(`${patient}.*Sent to pharmacy.*EVQ`),
      })
      .first(),
  ).toBeVisible()
})

/**
 * D-006: until the clinical safety ruling, the end date printed on the TGA letter is NOT covered
 * (half-open window). The UI must send that date unchanged, never "helpfully" add a day, because
 * that would fail wide. This pins it at the boundary.
 */
test("the letter's end date is sent unchanged and is itself not covered", async ({
  signedIn: page,
}) => {
  const sent: Array<{ valid_to?: string }> = []
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/v1/tga-approvals"))
      sent.push(r.postDataJSON())
  })
  // Recorded from the register.
  await page.goto("/approvals")
  await page.getByRole("button", { name: "Record approval" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("Patient").selectOption({ label: "Priya Sharma" })
  await dialog.getByLabel("TGA reference").fill("SAS-B 2026-555010")
  await dialog.getByLabel("Valid from").fill("2026-01-01")
  await dialog.getByLabel("Valid to (as on the letter)").fill("2027-06-30")
  await expect(dialog.getByText("the end date itself is")).toBeVisible()
  await dialog.getByRole("button", { name: "Record approval" }).click()
  await expect(dialog).toBeHidden()

  // The body on the wire carries the letter's date, not a "corrected" one.
  expect(sent).toHaveLength(1)
  expect(sent[0].valid_to).toBe("2027-06-30")

  // And the API's record shows it exactly as printed on the letter.
  await page.goto("/patients")
  await page.getByRole("cell", { name: "Priya Sharma" }).click()
  await page.getByRole("tab", { name: "TGA approvals" }).click()
  const row = page.getByRole("row", { name: /SAS-B 2026-555010/ })
  await expect(row).toContainText("30 June 2027")
})
