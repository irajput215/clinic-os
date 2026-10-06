import { expect, test } from "./fixtures"

/**
 * Consult notes against the real clinical_records module (`clinicalRecords: "api"`): write, sign and
 * amend a note, and see each step come back from the API on the patient's record.
 */
test("a consult note is written, signed and amended on the patient record", async ({
  signedIn: page,
}) => {
  const created: Array<{ soap?: Record<string, string> }> = []
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/v1/clinical-records"))
      created.push(r.postDataJSON())
  })

  await page.goto("/patients")
  await page.getByRole("cell", { name: "Dean Caruso" }).click()
  await page.getByRole("tab", { name: "Consult notes" }).click()
  await expect(page.getByText("No consult notes yet.")).toBeVisible()
  // Real clinical data: never labelled as sample data.
  await expect(page.getByText("Preview data.")).toHaveCount(0)

  // Write: two sections, two left blank.
  const save = page.getByRole("button", { name: "Save note" })
  await expect(save).toBeDisabled()
  await page.getByLabel("Subjective").fill("Knee pain, 6/10, worse on stairs.")
  await page.getByLabel("Plan").fill("Trial Category 1 oil. Review in 2 weeks.")
  await save.click()
  await expect(
    page.getByText("Note saved as a draft. Sign it to lock it."),
  ).toBeVisible()

  // Only the written sections are sent, so the stored note has no empty headings.
  expect(created).toHaveLength(1)
  expect(created[0].soap).toEqual({
    subjective: "Knee pain, 6/10, worse on stairs.",
    plan: "Trial Category 1 oil. Review in 2 weeks.",
  })

  const note = page.getByRole("listitem").filter({ hasText: "Knee pain" })
  await expect(note.getByText("Draft")).toBeVisible()
  // The API's Markdown narrative is shown as its SOAP sections.
  await expect(note.getByRole("term")).toHaveText(["Subjective", "Plan"])
  await expect(note.getByRole("definition").first()).toHaveText(
    "Knee pain, 6/10, worse on stairs.",
  )

  // Sign.
  await note.getByRole("button", { name: "Sign" }).click()
  await expect(
    page.getByText("Note signed. It can no longer be edited, only amended."),
  ).toBeVisible()
  await expect(note.getByText("Signed")).toBeVisible()
  await expect(note.getByRole("button", { name: "Sign" })).toHaveCount(0)

  // Amend: a reason is required, and the original is kept as version 1.
  await note.getByRole("button", { name: "Amend" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("Subjective")).toHaveValue(
    "Knee pain, 6/10, worse on stairs.",
  )
  const add = dialog.getByRole("button", { name: "Add amendment" })
  await expect(add).toBeDisabled()
  await dialog
    .getByLabel("Subjective")
    .fill("Knee pain, 5/10, worse on stairs.")
  await dialog.getByLabel("Reason for amendment").fill("Corrected pain score")
  await add.click()
  await expect(dialog).toBeHidden()

  // After a reload, everything shown comes from the API.
  await page.reload()
  const amended = page.getByRole("listitem").filter({ hasText: "Knee pain" })
  await expect(amended.getByText("Signed")).toBeVisible()
  await expect(amended.getByText("Amended · v2")).toBeVisible()
  await expect(amended).toContainText("Knee pain, 5/10, worse on stairs.")
  await expect(amended).toContainText("Amendment reason: Corrected pain score")
  await expect(page.getByText("Preview data.")).toHaveCount(0)
})
