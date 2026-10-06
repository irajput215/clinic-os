import { expect, test } from "./fixtures"

/**
 * TGA approvals against the real tga_approvals module (`tgaApprovals: "api"`). The patient's tab is
 * live end to end. The practice-wide register is a designed refusal until GET /tga-approvals exists.
 */
test("an approval is recorded, refused four-eyes, and revoked on the patient's tab", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("cell", { name: "Amira Hassan" }).click()
  await page.getByRole("tab", { name: "TGA approvals" }).click()
  await expect(page.getByText("No TGA approvals on file.")).toBeVisible()
  await expect(page.getByText("Preview data.")).toHaveCount(0)

  // Record.
  await page.getByRole("button", { name: "Record approval" }).click()
  const record = page.getByRole("dialog")
  await record.getByLabel("TGA category").selectOption("CATEGORY_4")
  await record.getByLabel("Dosage form").selectOption("CAPSULE")
  await record.getByLabel("TGA reference").fill("SAS-B 2026-880042")
  await record.getByLabel("Valid to (as on the letter)").fill("2027-09-30")
  await record.getByRole("button", { name: "Record approval" }).click()
  await expect(record).toBeHidden()
  const row = page.getByRole("row", { name: /SAS-B 2026-880042/ })
  await expect(row).toContainText("Pending verification")
  await expect(row).toContainText("Cat 4")

  // Verify: the server refuses the clinician who recorded it, in plain words.
  await row.getByRole("button", { name: "Verify" }).click()
  const verify = page.getByRole("dialog")
  await verify
    .getByLabel("TGA reference from the letter")
    .fill("SAS-B 2026-880042")
  await verify.getByRole("button", { name: "Verify and activate" }).click()
  await expect(verify.getByRole("alert")).toHaveText(
    "You entered this approval, so a second clinician must verify it.",
  )
  await verify.getByRole("button", { name: "Cancel" }).click()
  await expect(row).toContainText("Pending verification")

  // Revoke with a reason code.
  await row.getByRole("button", { name: "Revoke" }).click()
  const revoke = page.getByRole("dialog")
  await revoke.getByLabel("Reason").selectOption("ENTERED_IN_ERROR")
  await revoke.getByRole("button", { name: "Revoke" }).click()
  await expect(revoke).toBeHidden()

  // After a reload the state is the API's.
  await page.reload()
  const revoked = page.getByRole("row", { name: /SAS-B 2026-880042/ })
  await expect(revoked).toContainText("Revoked")
  await expect(revoked.getByRole("button")).toHaveCount(0)

  // The overview reads the same live list: nothing active.
  await page.getByRole("tab", { name: "Overview" }).click()
  await expect(
    page.getByText("No active TGA approval. Scripts will be blocked."),
  ).toBeVisible()
})

test("the practice-wide register says which endpoint it is waiting for", async ({
  signedIn: page,
}) => {
  const registerReads: string[] = []
  page.on("request", (r) => {
    if (r.method() === "GET" && r.url().endsWith("/api/v1/tga-approvals"))
      registerReads.push(r.url())
  })
  await page.goto("/approvals")

  const refusal = page.getByRole("status").filter({
    hasText: "The practice-wide register isn't available yet.",
  })
  await expect(refusal).toBeVisible()
  await expect(refusal).toContainText("GET /api/v1/tga-approvals")
  // No sample rows, no filter counts that would read as "zero approvals".
  await expect(page.getByText("Preview data.")).toHaveCount(0)
  await expect(
    page.getByRole("tablist", { name: "Filter approvals" }),
  ).toHaveCount(0)
  await expect(page.getByRole("table")).toHaveCount(0)
  // The refusal is decided in the client: nothing asks the API for a route it doesn't serve.
  expect(registerReads).toHaveLength(0)

  await refusal.getByRole("link", { name: "Open patients" }).click()
  await expect(page).toHaveURL(/\/patients$/)
})
