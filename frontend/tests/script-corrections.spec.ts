import { randomBytes } from "node:crypto"
import type { APIRequestContext } from "@playwright/test"
import { expect, test } from "./fixtures"

/**
 * Correcting a script (FEAT-11; docs2/sdlc/07-script-queue; decision D-008): a draft is edited in
 * place, cancelled with a reason and its history shows both; a signed script cannot be edited, only
 * amended by a new draft version that replaces it.
 *
 * Budget: no sign-in. The owner (who is also the prescriber of record here) and the setup project's
 * verifier act through their existing tokens. Each attempt stages scripts with a product name of its
 * own, so a retry never meets what an earlier attempt left, and the shared clinic's patients do not
 * change.
 */
const PATIENT = "Grace"
const GRAIN = { tga_category: "CATEGORY_3", dosage_form: "ORAL_OIL" }

const api = (request: APIRequestContext, token: string) => {
  const headers = { Authorization: `Bearer ${token}` }
  return {
    get: async <T>(path: string) => {
      const res = await request.get(`/api/v1${path}`, { headers })
      expect(res.ok(), await res.text()).toBeTruthy()
      return (await res.json()) as T
    },
    post: async <T>(path: string, data: unknown) => {
      const res = await request.post(`/api/v1${path}`, { headers, data })
      expect(res.ok(), await res.text()).toBeTruthy()
      return (await res.json()) as T
    },
    patch: (path: string, data: unknown) =>
      request.patch(`/api/v1${path}`, { headers, data }),
  }
}
type Api = ReturnType<typeof api>

async function stage(owner: Api, product: string) {
  const { data } = await owner.get<{
    data: { id: string; given_name: string }[]
  }>("/patients?limit=25")
  const patient = data.find((p) => p.given_name === PATIENT)
  expect(patient).toBeTruthy()
  const me = await owner.get<{ id: string }>("/users/me")
  return owner.post<{ id: string; patient_id: string }>("/prescriptions", {
    patient_id: patient!.id,
    prescriber_id: me.id,
    medicine_name: product,
    ...GRAIN,
    dose_instruction: "0.5 mL nocte",
    quantity: "1",
    repeats: 2,
    triage_outcome: "Eligible - chronic pain",
    conventional_therapy: "Paracetamol and NSAIDs for 6 months",
    date_of_service: new Date().toLocaleDateString("en-CA", {
      timeZone: "Australia/Sydney",
    }),
  })
}

/** An ACTIVE approval for the grain, recorded by the owner and verified by the second clinician. */
async function activeApproval(owner: Api, verifier: Api, patient: string) {
  type Approval = {
    id: string
    state: string
    tga_category: string
    dosage_form: string
    approval_reference: string
  }
  const { data: existing } = await owner.get<{ data: Approval[] }>(
    `/patients/${patient}/tga-approvals`,
  )
  let approval = existing.find(
    (a) =>
      a.tga_category === GRAIN.tga_category &&
      a.dosage_form === GRAIN.dosage_form &&
      (a.state === "ACTIVE" || a.state === "PENDING"),
  )
  if (approval?.state === "ACTIVE") return
  approval ??= await owner.post<Approval>("/tga-approvals", {
    patient_id: patient,
    ...GRAIN,
    approval_reference: `SAS-B 2026-${randomBytes(3).toString("hex")}`,
    creation_reason: "NEW_APPLICATION",
    valid_from: "2026-01-01",
    valid_to: "2027-12-31",
  })
  await verifier.post(`/tga-approvals/${approval.id}/verify`, {
    tga_application_number: approval.approval_reference,
  })
}

test("a draft is edited, cancelled with a reason, and its history shows both", async ({
  signedIn: page,
  clinic,
  request,
}) => {
  const owner = api(request, clinic.token)
  const product = `Correctable Oil ${randomBytes(2).toString("hex")}`
  const script = await stage(owner, product)

  await page.goto("/scripts")
  const card = page.locator("article", { hasText: product })
  await card.getByRole("button", { name: "Review & sign" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Edit draft" }).click()
  await expect(
    dialog.getByRole("heading", { name: "Edit draft" }),
  ).toBeVisible()
  await dialog.getByLabel("Repeats").fill("4")
  await dialog.getByLabel("Directions").fill("1 mL nocte")
  await dialog.getByRole("button", { name: "Save draft" }).click()
  await expect(page.getByText("Draft updated.")).toBeVisible()
  await expect(card).toContainText("4 repeats")
  await expect(card).toContainText("1 mL nocte")

  await card.getByRole("button", { name: "Review & sign" }).click()
  await dialog.getByRole("button", { name: "Cancel script" }).click()
  // The reason is required: an empty choice is refused before anything is sent.
  await dialog.getByRole("button", { name: "Cancel script" }).click()
  await expect(dialog.getByText("Choose why it is cancelled.")).toBeVisible()
  await dialog.getByLabel("Reason").selectOption({ label: "Patient declined" })
  await dialog.getByRole("button", { name: "Cancel script" }).click()
  await expect(page.getByText("Script cancelled.")).toBeVisible()
  await expect(card).toHaveCount(0)

  // The patient's Scripts tab lists it as cancelled, with its history.
  await page.goto(`/patients/${script.patient_id}?tab=scripts`)
  await page.getByRole("button", { name: `History of ${product}` }).click()
  const history = page.getByTestId("script-history")
  await expect(history).toContainText("Staged: Awaiting review")
  await expect(history).toContainText("Awaiting review → Cancelled")
  await expect(history).toContainText("Patient declined")
})

test("a signed script cannot be edited; it is amended by a new draft that replaces it", async ({
  signedIn: page,
  clinic,
  request,
}) => {
  test.setTimeout(60_000)
  const owner = api(request, clinic.token)
  const product = `Signed Oil ${randomBytes(2).toString("hex")}`
  const script = await stage(owner, product)
  await activeApproval(
    owner,
    api(request, clinic.verifier.token),
    script.patient_id,
  )
  const { step_up_token } = await owner.post<{ step_up_token: string }>(
    "/auth/step-up",
    {
      password: clinic.password,
      operation: "prescription.sign",
      resource_id: script.id,
    },
  )
  await owner.post(`/prescriptions/${script.id}/sign`, { step_up_token })

  // The server refuses an edit of a signed script, whatever a client tries.
  const edit = await owner.patch(`/prescriptions/${script.id}`, { repeats: 1 })
  expect(edit.status()).toBe(409)

  await page.goto("/scripts")
  const card = page.locator("article", { hasText: product })
  await card.getByRole("button", { name: "Review & send" }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByRole("button", { name: "Amend" })).toBeVisible()
  await expect(dialog.getByRole("button", { name: "Edit draft" })).toHaveCount(
    0,
  )
  await dialog.getByRole("button", { name: "Amend" }).click()
  await dialog.getByLabel("Directions").fill("0.25 mL nocte")
  await dialog.getByRole("button", { name: "Draft addendum" }).click()
  await expect(
    page.getByText(
      "Addendum drafted. Review and sign it to replace the original.",
    ),
  ).toBeVisible()
  // The queue now holds the new draft, and the original is gone from it.
  await expect(card).toHaveCount(1)
  await expect(card).toContainText("0.25 mL nocte")
  await expect(
    card.getByRole("button", { name: "Review & sign" }),
  ).toBeVisible()
})
