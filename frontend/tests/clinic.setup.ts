import { randomBytes } from "node:crypto"
import { mkdirSync, writeFileSync } from "node:fs"
import { type APIRequestContext, expect, test as setup } from "@playwright/test"
import { signInWithApi, signUp, verifySignupByEmail } from "./accounts"
import { CLINIC_FILE, type Clinic } from "./fixtures"
import { emailedPath, waitForEmailHtml } from "./mail"
import { previousRunWindowLeft } from "./pacing"

/**
 * One fresh clinic per run, created the way a real practice is: `POST /users/signup` with a clinic
 * name, then the emailed link (read from Mailpit), makes a new organisation and its practice
 * owner. Patients are then added through the API.
 */
const PATIENTS = [
  ["Marcus", "Webb", "1979-04-12", "MALE"],
  ["Priya", "Sharma", "1991-09-03", "FEMALE"],
  ["Dean", "Caruso", "1968-01-22", "MALE"],
  ["Amira", "Hassan", "1985-06-30", "FEMALE"],
  ["Willem", "Barker", "1957-11-08", "MALE"],
  ["Grace", "Liu", "1994-02-17", "FEMALE"],
] as const

async function completePack(
  request: APIRequestContext,
  auth: { authorization: string },
  password: string,
  userId: string,
) {
  const agreement = await request.post(`/api/v1/users/${userId}/agreements`, {
    headers: auth,
    data: { agreement_version: "2026-1", signed_on: "2026-01-05" },
  })
  expect(agreement.status(), await agreement.text()).toBe(201)
  const digits = (n: number) =>
    Array.from({ length: n }, () => Math.floor(Math.random() * 10)).join("")
  for (const [kind, value] of [
    ["AHPRA", `MED${digits(10)}`],
    ["PRESCRIBER_NUMBER", digits(7)],
  ]) {
    const grant = await request.post("/api/v1/auth/step-up", {
      headers: auth,
      data: {
        password,
        operation: "practitioner.identifier_update",
        resource_id: userId,
      },
    })
    expect(grant.status(), await grant.text()).toBe(201)
    const saved = await request.put(
      `/api/v1/users/${userId}/identifiers/${kind}`,
      {
        headers: auth,
        data: {
          value,
          status: "ACTIVE",
          verification_method: "AHPRA public register",
          step_up_token: ((await grant.json()) as { step_up_token: string })
            .step_up_token,
        },
      },
    )
    expect(saved.ok(), await saved.text()).toBeTruthy()
  }
}

setup("sign up a clinic and add patients", async ({ request, baseURL }) => {
  // A run straight after another against the same backend waits out the window that one left,
  // before anything here spends a sign-in (`pacing.ts`).
  const wait = previousRunWindowLeft(new URL(baseURL!).origin)
  setup.setTimeout(wait + 60_000)
  if (wait > 0) {
    console.log(
      `Waiting ${Math.ceil(wait / 1000)}s for the previous run's rate-limit window to pass`,
    )
    await new Promise((resolve) => setTimeout(resolve, wait))
  }

  const run = randomBytes(4).toString("hex")
  // Deliberately not the reference design's sample clinic, so a screen still showing the sample
  // name cannot pass for showing this one.
  const clinicName = `Ironbark Medical ${run}`
  const clinic: Omit<Clinic, "token" | "peer" | "verifier"> = {
    email: `owner-${run}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
    fullName: "Dr Sarah Okafor",
    // backend/app/modules/identity_tenancy/service.py `slugify`: lower-case, hyphenated.
    slug: `ironbark-medical-${run}`,
    // Signup sets the display name from the clinic name (`signup_display_name`).
    name: clinicName,
  }

  const signup = await request.post("/api/v1/users/signup", {
    data: {
      email: clinic.email,
      password: clinic.password,
      full_name: clinic.fullName,
      clinic_name: clinicName,
    },
  })
  expect(signup.status(), await signup.text()).toBe(202)
  // Nothing exists until the emailed link is used (D-008); using it signs the owner in, so the
  // setup spends no sign-in of its own on the owner.
  const access_token = await verifySignupByEmail(request, clinic.email)
  const auth = { authorization: `Bearer ${access_token}` }

  // The owner also consults: granting the Doctor role makes them a bookable practitioner, so the
  // calendar has a column and the public booking page offers doctor consults. Practitioners are
  // derived from roles on the server (appointments module); there is no roster to seed.
  const roles = await request.get("/api/v1/roles", { headers: auth })
  expect(roles.ok(), await roles.text()).toBeTruthy()
  const doctor = (
    (await roles.json()) as { data: { id: string; code: string }[] }
  ).data.find((role) => role.code === "DOCTOR")
  expect(doctor).toBeDefined()
  const me = await request.get("/api/v1/users/me", { headers: auth })
  expect(me.ok(), await me.text()).toBeTruthy()
  const ownerId = ((await me.json()) as { id: string }).id
  const granted = await request.post(`/api/v1/users/${ownerId}/roles`, {
    headers: auth,
    data: { role_id: doctor?.id },
  })
  expect(granted.ok(), await granted.text()).toBeTruthy()

  for (const [
    given_name,
    family_name,
    date_of_birth,
    sex_at_birth,
  ] of PATIENTS) {
    const res = await request.post("/api/v1/patients", {
      headers: { authorization: `Bearer ${access_token}` },
      data: {
        given_name,
        family_name,
        date_of_birth,
        sex_at_birth,
        state: "VIC",
      },
    })
    expect(res.status(), await res.text()).toBe(201)
  }

  // A second clinic's owner, for the tests that change their own name or roles (`fixtures.ts`).
  const peer = await signUp(request, { clinic: true })
  const peerToken = await signInWithApi(request, peer)

  // A second clinician in this clinic, the four-eyes verifier of TGA approvals (`fixtures.ts`):
  // invited by the owner, accepted through the emailed link's token, signed in once.
  const verifier = {
    email: `verifier-${run}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
    fullName: "Dr Tom Verifier",
  }
  const invited = await request.post("/api/v1/users/staff", {
    headers: auth,
    data: {
      email: verifier.email,
      full_name: verifier.fullName,
      role_ids: [doctor?.id],
    },
  })
  expect(invited.ok(), await invited.text()).toBeTruthy()
  const link = emailedPath(
    await waitForEmailHtml(request, verifier.email),
    "/accept-invite",
  )
  const accepted = await request.post("/api/v1/users/invitations/accept", {
    data: {
      token: new URL(link, "http://x").searchParams.get("token"),
      new_password: verifier.password,
    },
  })
  expect(accepted.ok(), await accepted.text()).toBeTruthy()
  const verifierToken = await signInWithApi(request, verifier)
  const verifierId = (
    (await (
      await request.get("/api/v1/users/me", {
        headers: { authorization: `Bearer ${verifierToken}` },
      })
    ).json()) as { id: string }
  ).id

  // Both doctors may sign scripts only with a complete onboarding pack (docs3 feature 02): the owner
  // records each one's agreement and verifies their AHPRA and prescriber numbers, with a step-up each.
  for (const userId of [ownerId, verifierId])
    await completePack(request, auth, clinic.password, userId)

  mkdirSync("playwright/.auth", { recursive: true })
  writeFileSync(
    CLINIC_FILE,
    JSON.stringify({
      ...clinic,
      token: access_token,
      peer: { ...peer, token: peerToken },
      verifier: { ...verifier, token: verifierToken },
    } satisfies Clinic),
  )
})
