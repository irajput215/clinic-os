import { randomBytes } from "node:crypto"
import { mkdirSync, writeFileSync } from "node:fs"
import { expect, test as setup } from "@playwright/test"
import { signInWithApi, signUp } from "./accounts"
import { CLINIC_FILE, type Clinic } from "./fixtures"
import { previousRunWindowLeft } from "./pacing"

/**
 * One fresh clinic per run, created the way a real practice is: `POST /users/signup` with a clinic
 * name makes a new organisation and its practice owner. Patients are then added through the API.
 */
const PATIENTS = [
  ["Marcus", "Webb", "1979-04-12", "MALE"],
  ["Priya", "Sharma", "1991-09-03", "FEMALE"],
  ["Dean", "Caruso", "1968-01-22", "MALE"],
  ["Amira", "Hassan", "1985-06-30", "FEMALE"],
  ["Willem", "Barker", "1957-11-08", "MALE"],
  ["Grace", "Liu", "1994-02-17", "FEMALE"],
] as const

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
  const clinic: Omit<Clinic, "token" | "peer"> = {
    email: `owner-${run}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
    fullName: "Dr Sarah Okafor",
    // backend/app/modules/identity_tenancy/service.py `slugify`: lower-case, hyphenated.
    slug: `ironbark-medical-${run}`,
  }

  const signup = await request.post("/api/v1/users/signup", {
    data: {
      email: clinic.email,
      password: clinic.password,
      full_name: clinic.fullName,
      clinic_name: clinicName,
    },
  })
  expect(signup.ok(), await signup.text()).toBeTruthy()

  const access_token = await signInWithApi(request, clinic)
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
  const ownerId = ((await signup.json()) as { id: string }).id
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

  mkdirSync("playwright/.auth", { recursive: true })
  writeFileSync(
    CLINIC_FILE,
    JSON.stringify({
      ...clinic,
      token: access_token,
      peer: { ...peer, token: peerToken },
    } satisfies Clinic),
  )
})
