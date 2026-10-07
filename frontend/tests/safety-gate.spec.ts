import { randomBytes } from "node:crypto"
import type { APIRequestContext } from "@playwright/test"
import { expect, test } from "./fixtures"
import { emailedPath, waitForEmailHtml } from "./mail"

/**
 * The prescription safety gate, as the clinician meets it, against the real prescriptions API: the
 * gate's answer on every card comes from the server, and the server decides again inside the
 * signing and dispatch transactions. Signing re-enters the password through the server-side step-up
 * (`POST /auth/step-up`); no pharmacy transport exists, so a signed script is "queued, not sent".
 */
const api = (request: APIRequestContext, token: string) => ({
  get: async <T>(path: string) => {
    const res = await request.get(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
    return (await res.json()) as T
  },
  post: async <T>(path: string, data: unknown) => {
    const res = await request.post(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      data,
    })
    expect(res.ok(), await res.text()).toBeTruthy()
    return (await res.json()) as T
  },
})

const patientId = async (
  owner: ReturnType<typeof api>,
  given: string,
): Promise<string> => {
  const { data } = await owner.get<{
    data: { id: string; given_name: string }[]
  }>("/patients?limit=100")
  const found = data.find((p) => p.given_name === given)
  expect(found, `patient ${given}`).toBeTruthy()
  return found!.id
}

/**
 * An ACTIVE approval needs a second clinician (four-eyes): invite a doctor into the clinic, accept
 * through the emailed link's token, sign in once as them, and verify the owner's entry.
 */
const activeApproval = async (
  request: APIRequestContext,
  owner: ReturnType<typeof api>,
  patient: string,
  grain: { tga_category: string; dosage_form: string },
) => {
  const { data: roles } = await owner.get<{
    data: { id: string; code: string }[]
  }>("/roles")
  const doctorRole = roles.find((r) => r.code === "DOCTOR")!
  const doctor = {
    email: `doctor-${randomBytes(4).toString("hex")}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
  }
  await owner.post("/users/staff", {
    email: doctor.email,
    full_name: "Dr Tom Verifier",
    role_ids: [doctorRole.id],
  })
  const link = emailedPath(
    await waitForEmailHtml(request, doctor.email),
    "/accept-invite",
  )
  const token = new URL(link, "http://x").searchParams.get("token")
  const accepted = await request.post("/api/v1/users/invitations/accept", {
    data: { token, new_password: doctor.password },
  })
  expect(accepted.ok(), await accepted.text()).toBeTruthy()
  const login = await request.post("/api/v1/login/access-token", {
    form: { username: doctor.email, password: doctor.password },
  })
  expect(login.ok(), await login.text()).toBeTruthy()
  const doctorApi = api(
    request,
    ((await login.json()) as { access_token: string }).access_token,
  )
  const reference = `SAS-B 2026-${randomBytes(3).toString("hex")}`
  const approval = await owner.post<{ id: string }>("/tga-approvals", {
    patient_id: patient,
    ...grain,
    approval_reference: reference,
    creation_reason: "NEW_APPLICATION",
    valid_from: "2026-01-01",
    valid_to: "2027-12-31",
  })
  await doctorApi.post(`/tga-approvals/${approval.id}/verify`, {
    tga_application_number: reference,
  })
}

test("a script with no covering approval cannot be signed", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("cell", { name: "Grace Liu" }).click()
  // Nothing in this patient's approvals covers Category 3 capsules.
  await page.getByRole("tab", { name: "Scripts" }).click()
  await page.getByRole("button", { name: "Stage a script" }).click()
  const stage = page.getByRole("dialog")
  await stage.getByLabel("Product").fill("Aurora 10 Capsules")
  await stage.getByLabel("TGA category").selectOption("CATEGORY_3")
  await stage.getByLabel("Dosage form").selectOption("CAPSULE")
  await stage.getByLabel("Directions / titration").fill("1 capsule nocte")
  await stage.getByLabel("Triage outcome").fill("Eligible - insomnia")
  await stage
    .getByLabel("Conventional therapy first")
    .fill("Sleep hygiene, melatonin 6 months")
  await stage.getByRole("button", { name: "Stage draft" }).click()
  await expect(
    page.getByText("It can't be signed until one does."),
  ).toBeVisible()

  const card = page.locator("article", { hasText: "Aurora 10 Capsules" })
  await expect(card).toContainText("No TGA approval on file for this patient")
  await card.getByRole("button", { name: "Review & sign" }).click()
  const review = page.getByRole("dialog")
  await expect(review.getByRole("status")).toContainText(
    "Safety gate: blocked.",
  )
  await expect(review.getByRole("status")).toContainText(
    "TGA_APPROVAL_NOT_FOUND",
  )
  await expect(review.getByLabel("Your password, to sign")).toBeDisabled()
  await expect(
    review.getByRole("button", { name: "Sign & queue for pharmacy" }),
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

test("a covered script is signed with a password re-entry and queued, not sent", async ({
  signedIn: page,
  clinic,
  request,
}) => {
  test.setTimeout(60_000)
  const owner = api(request, clinic.token)
  const dean = await patientId(owner, "Dean")
  const grain = { tga_category: "CATEGORY_2", dosage_form: "ORAL_LIQUID" }
  await activeApproval(request, owner, dean, grain)
  const me = await owner.get<{ id: string }>("/users/me")
  await owner.post("/prescriptions", {
    patient_id: dean,
    prescriber_id: me.id,
    medicine_name: "Solace CBD Oil 50",
    ...grain,
    dose_instruction: "0.5 mL twice daily",
    quantity: "1",
    repeats: 2,
    triage_outcome: "Eligible - chronic pain",
    conventional_therapy: "NSAIDs and physiotherapy, 9 months",
    date_of_service: new Date().toLocaleDateString("en-CA", {
      timeZone: "Australia/Sydney",
    }),
  })

  await page.goto("/scripts")
  const card = page.locator("article", { hasText: "Solace CBD Oil 50" })
  await expect(card).toContainText("Covered through")
  await card.getByRole("button", { name: "Review & sign" }).click()
  const review = page.getByRole("dialog")
  await expect(review.getByRole("status")).toContainText("Safety gate: clear.")

  // The server checks the password; a wrong one signs nothing and keeps the session.
  await review.getByLabel("Your password, to sign").fill("wrong-password")
  await review
    .getByRole("button", { name: "Sign & queue for pharmacy" })
    .click()
  await expect(review.getByRole("alert")).toHaveText(
    "That password isn't right. Re-enter it to continue.",
  )

  await review.getByLabel("Your password, to sign").fill(clinic.password)
  await review
    .getByRole("button", { name: "Sign & queue for pharmacy" })
    .click()
  await expect(
    page.getByText(
      "Signed and queued. Not sent: no pharmacy connection is configured yet.",
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("row", {
      name: /Dean Caruso.*Solace CBD Oil 50.*Queued, not sent/,
    }),
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
