import { randomInt } from "node:crypto"
import type { APIRequestContext } from "@playwright/test"
import { expect, test } from "./fixtures"

/**
 * The Today page against the real `GET /api/v1/dashboard/today`. Everything it shows is created here
 * through the API, for a patient made fresh for each attempt, so the assertions find this test's own
 * rows on a clinic other specs write to at the same time.
 */
const api = (request: APIRequestContext, token: string) => ({
  get: async <T>(path: string) => {
    const res = await request.get(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(res.ok(), await res.text()).toBeTruthy()
    return (await res.json()) as T
  },
  post: (path: string, data: unknown) =>
    request.post(`/api/v1${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      data,
    }),
})

const sydney = (d: Date) =>
  d.toLocaleDateString("en-CA", { timeZone: "Australia/Sydney" })
const addDays = (iso: string, days: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
/** A name the patient schema accepts (letters only), different on every attempt. */
const letters = (n: number) =>
  Array.from({ length: n }, () => String.fromCharCode(97 + randomInt(26))).join(
    "",
  )

test("Today shows the clinic's day from the API", async ({
  signedIn: page,
  clinic,
  request,
}) => {
  const owner = api(request, clinic.token)
  const verifier = api(request, clinic.verifier.token)
  const me = await owner.get<{ id: string }>("/users/me")
  const today = sydney(new Date())
  const family = `Today${letters(6)}`
  const patientName = `Iris ${family[0].toUpperCase()}${family.slice(1)}`

  const created = await owner.post("/patients", {
    given_name: "Iris",
    family_name: family[0].toUpperCase() + family.slice(1),
    date_of_birth: "1980-05-05",
    sex_at_birth: "FEMALE",
    state: "VIC",
  })
  expect(created.status(), await created.text()).toBe(201)
  const patient = ((await created.json()) as { id: string }).id

  // A booking today with the owner (the clinic's bookable doctor), early, at a time no other spec
  // books; a clash with an earlier attempt moves to the next quarter hour.
  let bookedAt = ""
  for (let slot = randomInt(0, 20); !bookedAt; slot++) {
    expect(slot, "a free early slot today").toBeLessThan(28)
    const hh = String(Math.floor(slot / 4)).padStart(2, "0")
    const mm = String((slot % 4) * 15).padStart(2, "0")
    const res = await owner.post("/appointments", {
      patient_id: patient,
      practitioner_id: me.id,
      type: "FOLLOW_UP",
      starts_at: new Date(
        `${today}T${hh}:${mm}:00${sydneyOffset(today, hh)}`,
      ).toISOString(),
    })
    if (res.status() === 201) bookedAt = `${hh}:${mm}`
    else expect(res.status(), await res.text()).toBe(409)
  }

  // An active approval whose last covered day is ten days away: a renewal, and needs attention.
  const reference = `SAS-B 2026-${letters(6).toUpperCase()}`
  const recorded = await owner.post("/tga-approvals", {
    patient_id: patient,
    tga_category: "CATEGORY_2",
    dosage_form: "ORAL_LIQUID",
    approval_reference: reference,
    creation_reason: "NEW_APPLICATION",
    valid_from: addDays(today, -60),
    valid_to: addDays(today, 11),
  })
  expect(recorded.status(), await recorded.text()).toBe(201)
  const approval = (await recorded.json()) as { id: string }
  const verified = await verifier.post(`/tga-approvals/${approval.id}/verify`, {
    tga_application_number: reference,
  })
  expect(verified.ok(), await verified.text()).toBeTruthy()

  // A draft for a grain that approval does not cover: the gate blocks it, live.
  const product = `Today Check Oil ${letters(4)}`
  const staged = await owner.post("/prescriptions", {
    patient_id: patient,
    prescriber_id: me.id,
    medicine_name: product,
    tga_category: "CATEGORY_3",
    dosage_form: "ORAL_LIQUID",
    dose_instruction: "0.5 mL nocte",
    quantity: "1",
    repeats: 0,
    triage_outcome: "Eligible - chronic pain",
    conventional_therapy: "NSAIDs for 6 months",
    date_of_service: today,
  })
  expect(staged.status(), await staged.text()).toBe(201)

  const reads: string[] = []
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/")) reads.push(new URL(r.url()).pathname)
  })
  await page.goto("/")
  await expect(
    page.getByRole("heading", { name: "Today's clinic" }),
  ).toBeVisible()
  await expect(page.getByText("Preview data")).toHaveCount(0)
  // One request for the page's data (R1 non-functional), besides the shell's own reads.
  expect(reads.filter((p) => p.startsWith("/api/v1/dashboard"))).toEqual([
    "/api/v1/dashboard/today",
  ])

  // The schedule: this test's booking, with its time, practitioner and status.
  const schedule = page.getByRole("region", { name: "Today's schedule" })
  const booking = schedule.getByRole("row", { name: new RegExp(patientName) })
  await expect(booking).toContainText(bookedAt)
  await expect(booking).toContainText("Dr Sarah Okafor")
  await expect(booking).toContainText("Booked")

  // The staging queue: the draft, blocked by the gate the server evaluated now.
  const queue = page.getByRole("region", { name: "Script staging queue" })
  const script = queue.getByRole("listitem").filter({ hasText: product })
  await expect(script).toContainText(patientName)
  await expect(script).toContainText("Blocked · Wrong category")
  // The tile counts scripts the gate refuses now, this draft among them.
  await expect(
    page.getByRole("link", { name: /Scripts needing action/ }),
  ).toContainText(/\d+\+? blocked on approval/)

  // Renewals and needs attention: the approval ending in ten days.
  const renewals = page.getByRole("region", { name: "SAS-B / AP renewals" })
  const renewal = renewals.getByRole("row", { name: new RegExp(reference) })
  await expect(renewal).toContainText(patientName)
  await expect(renewal).toContainText("10 days")
  await expect(
    page
      .getByRole("region", { name: "Needs attention" })
      .getByRole("link", { name: new RegExp(`ends in 10 d - ${patientName}`) }),
  ).toBeVisible()

  // The tiles link to the screens that fix things; the renewal tile opens "Needs action".
  await page.getByRole("link", { name: /Approvals expiring/ }).click()
  await expect(page).toHaveURL(/\/approvals\?filter=attention$/)
  await page.goBack()

  // A schedule row opens the patient.
  await booking.click()
  await expect(
    page.getByRole("heading", { name: patientName, exact: true }),
  ).toBeVisible()
})

/** Sydney's UTC offset at `hh`:00 on `day`, as `+11:00` or `+10:00`. */
function sydneyOffset(day: string, hh: string): string {
  const probe = new Date(`${day}T${hh}:00:00Z`)
  const name = new Intl.DateTimeFormat("en-AU", {
    timeZone: "Australia/Sydney",
    timeZoneName: "longOffset",
  })
    .formatToParts(probe)
    .find((p) => p.type === "timeZoneName")?.value
  return (name ?? "GMT+10:00").replace("GMT", "")
}
