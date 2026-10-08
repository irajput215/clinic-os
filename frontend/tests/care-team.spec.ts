import type { APIRequestContext, APIResponse } from "@playwright/test"
import { expect, openSignedIn, test } from "./fixtures"

/**
 * The treating-relationship rule (T1-34, decision D-007; docs2/sdlc/02-patients). A doctor reaches a
 * patient's record only while on the patient's care team: off it, the record is refused politely and
 * says nothing about the patient; added to it by the practice owner on the Care team card, the record
 * opens; ended, it is refused again.
 *
 * Budget: no sign-in. The doctor is the setup project's verifier (a Doctor-only account in the shared
 * clinic, already signed in) and the owner is the setup project's owner. The care-team writes are in
 * the administrative 20-a-minute window the owner shares with other specs, so the test's own calls
 * wait out a `429` the way the screen would. The patient is one of the six the setup project created,
 * so the shared clinic's patient count does not move; the test leaves the team as it found it.
 */
const PATIENT = { given: "Willem", family: "Barker" }

async function outlast429(send: () => Promise<APIResponse>) {
  for (let attempt = 0; ; attempt++) {
    const response = await send()
    if (response.status() !== 429 || attempt === 3) return response
    const wait = Number(response.headers()["retry-after"] ?? "5")
    await new Promise((resolve) => setTimeout(resolve, (wait + 1) * 1000))
  }
}

const auth = (token: string) => ({ Authorization: `Bearer ${token}` })

async function patientId(request: APIRequestContext, token: string) {
  const found = await request.post("/api/v1/patients/search", {
    headers: auth(token),
    data: { q: `${PATIENT.given} ${PATIENT.family}` },
  })
  expect(found.ok(), await found.text()).toBeTruthy()
  const [patient] = (await found.json()).data as { id: string }[]
  expect(patient).toBeDefined()
  return patient.id
}

/** A retried attempt starts from an empty team: end anything an earlier attempt left. */
async function emptyTeam(
  request: APIRequestContext,
  token: string,
  id: string,
) {
  const team = await outlast429(() =>
    request.get(`/api/v1/patients/${id}/care-relationships`, {
      headers: auth(token),
    }),
  )
  expect(team.ok(), await team.text()).toBeTruthy()
  for (const member of (await team.json()).data as { id: string }[]) {
    const ended = await outlast429(() =>
      request.post(
        `/api/v1/patients/${id}/care-relationships/${member.id}/end`,
        { headers: auth(token) },
      ),
    )
    expect(ended.ok(), await ended.text()).toBeTruthy()
  }
}

test("a doctor off the care team is refused politely; on it, the record opens", async ({
  signedIn: ownerPage,
  clinic,
  request,
  browser,
}) => {
  const id = await patientId(request, clinic.token)
  await emptyTeam(request, clinic.token, id)

  // The doctor, in a context of their own.
  const doctorContext = await browser.newContext()
  const doctorPage = await doctorContext.newPage()
  await openSignedIn(doctorPage, clinic.verifier.token, `/patients/${id}`)
  const refusal = doctorPage.getByTestId("no-care-relationship")
  await expect(refusal).toBeVisible()
  await expect(refusal).toContainText(
    "You have no care relationship with this patient.",
  )
  // Nothing about the record leaks into the refusal: not the name, not a tab.
  await expect(doctorPage.getByText(PATIENT.family)).toHaveCount(0)
  await expect(doctorPage.getByRole("tab")).toHaveCount(0)
  // Their own list says why it is empty of this patient.
  await doctorPage.goto("/patients")
  await expect(doctorPage.getByText(PATIENT.family)).toHaveCount(0)

  // The owner adds the doctor on the record's Care team card.
  await ownerPage.goto(`/patients/${id}`)
  const card = ownerPage.getByRole("region", { name: "Care team" })
  await expect(card.getByText("No one yet.")).toBeVisible()
  await card
    .getByLabel("Add a clinician")
    .selectOption({ label: `${clinic.verifier.fullName} (Doctor)` })
  await card.getByRole("button", { name: "Add" }).click()
  await expect(card.getByTestId("care-team")).toContainText(
    clinic.verifier.fullName,
  )

  // On the team, the record opens for the doctor.
  await doctorPage.goto(`/patients/${id}`)
  await expect(
    doctorPage.getByRole("heading", {
      name: `${PATIENT.given} ${PATIENT.family}`,
    }),
  ).toBeVisible()
  await expect(doctorPage.getByTestId("no-care-relationship")).toHaveCount(0)
  // And the doctor sees no Care team card: their own access is relationship-bound.
  await expect(
    doctorPage.getByRole("region", { name: "Care team" }),
  ).toHaveCount(0)

  // Ended by the owner, the record is refused again.
  await card
    .getByRole("button", {
      name: `End care relationship with ${clinic.verifier.fullName}`,
    })
    .click()
  await expect(card.getByText("No one yet.")).toBeVisible()
  await doctorPage.reload()
  await expect(doctorPage.getByTestId("no-care-relationship")).toBeVisible()
  await doctorContext.close()
})
