import { expect, test } from "./fixtures"

/**
 * TGA approvals against the real tga_approvals module (`tgaApprovals: "api"`): the patient's tab and
 * the practice-wide register (GET /api/v1/tga-approvals) are live end to end.
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

test("the practice-wide register lists, filters and counts the practice's approvals", async ({
  signedIn: page,
}) => {
  const registerReads: URL[] = []
  page.on("request", (r) => {
    const url = new URL(r.url())
    if (r.method() === "GET" && url.pathname === "/api/v1/tga-approvals")
      registerReads.push(url)
  })

  await page.goto("/approvals")
  const filters = page.getByRole("navigation", { name: "Filter approvals" })
  await expect(
    filters.getByRole("link", { name: /Needs action/ }),
  ).toHaveAttribute("aria-current", "page")
  await expect(page.getByText("Preview data.")).toHaveCount(0)
  await expect(page.getByText("isn't available yet")).toHaveCount(0)

  // Record from the register: it lands pending, so it needs action.
  await page.getByRole("button", { name: "Record approval" }).click()
  const record = page.getByRole("dialog")
  // The picker asks the server's search, so every patient is reachable, not only the first page.
  await record.getByLabel("Patient", { exact: true }).fill("Barker")
  await record
    .getByRole("radiogroup", { name: "Matching patients" })
    .getByRole("radio", { name: /Willem Barker/ })
    .check()
  await record.getByLabel("TGA category").selectOption("CATEGORY_1")
  await record.getByLabel("Dosage form").selectOption("ORAL_LIQUID")
  await record.getByLabel("TGA reference").fill("SAS-B 2026-660123")
  await record.getByLabel("Valid to (as on the letter)").fill("2027-08-31")
  await record.getByRole("button", { name: "Record approval" }).click()
  await expect(record).toBeHidden()

  const row = page.getByRole("row", { name: /SAS-B 2026-660123/ })
  await expect(row).toContainText("Willem Barker")
  await expect(row).toContainText("Pending verification")
  await expect(
    page.getByText(/^Showing \d+ of \d+, newest first$/),
  ).toBeVisible()

  // "Needs action" is one server query: pending, or active and expiring within 30 days.
  expect(
    registerReads.some(
      (u) =>
        u.searchParams.getAll("state").join() === "PENDING" &&
        u.searchParams.get("expiring_within_days") === "30",
    ),
  ).toBe(true)
  // No patient identifier and no tenant ever travels in the register's URL.
  for (const u of registerReads) {
    expect(u.searchParams.has("tenant_id")).toBe(false)
    expect(u.searchParams.has("patient_id")).toBe(false)
  }

  // The filter is in the page URL and every chip carries the practice's count.
  await filters.getByRole("link", { name: /^Pending/ }).click()
  await expect(page).toHaveURL(/\/approvals\?filter=pending$/)
  await expect(
    page.getByRole("row", { name: /SAS-B 2026-660123/ }),
  ).toBeVisible()
  for (const name of [
    /Needs action \d+/,
    /Active \d+/,
    /Pending \d+/,
    /All \d+/,
  ])
    await expect(filters.getByRole("link", { name })).toBeVisible()

  // Revoked, it leaves Pending and is under Expired & revoked.
  await page
    .getByRole("row", { name: /SAS-B 2026-660123/ })
    .getByRole("button", { name: "Revoke" })
    .click()
  const revoke = page.getByRole("dialog")
  await revoke.getByLabel("Reason").selectOption("ENTERED_IN_ERROR")
  await revoke.getByRole("button", { name: "Revoke" }).click()
  await expect(revoke).toBeHidden()
  await expect(
    page.getByRole("row", { name: /SAS-B 2026-660123/ }),
  ).toHaveCount(0)

  await filters.getByRole("link", { name: /Expired & revoked/ }).click()
  const revoked = page.getByRole("row", { name: /SAS-B 2026-660123/ })
  await expect(revoked).toContainText("Revoked")
  await expect(revoked.getByRole("button")).toHaveCount(0)

  // The row links to the patient's own approvals tab.
  await revoked.getByRole("link", { name: "Willem Barker" }).click()
  await expect(page).toHaveURL(/\/patients\/[^/]+\?tab=approvals$/)
  await expect(
    page.getByRole("row", { name: /SAS-B 2026-660123/ }),
  ).toContainText("Revoked")

  // Back returns to the filter the user left.
  await page.goBack()
  await expect(
    filters.getByRole("link", { name: /Expired & revoked/ }),
  ).toHaveAttribute("aria-current", "page")
})

test("the register never scrolls the page sideways at phone width", async ({
  signedIn: page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/approvals?filter=all")
  await expect(page.getByText(/newest first|No TGA approvals/)).toBeVisible()
  // The table scrolls inside its card; the page itself must not.
  const overflow = await page.evaluate(
    () => (document.scrollingElement?.scrollWidth ?? 0) - window.innerWidth,
  )
  expect(overflow).toBe(0)
})
