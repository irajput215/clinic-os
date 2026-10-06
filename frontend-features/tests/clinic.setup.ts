import { randomBytes } from "node:crypto"
import { mkdirSync, writeFileSync } from "node:fs"
import { expect, test as setup } from "@playwright/test"
import { CLINIC_FILE, type Clinic } from "./fixtures"

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

setup("sign up a clinic and add patients", async ({ request }) => {
  const run = randomBytes(4).toString("hex")
  const clinic: Clinic = {
    email: `owner-${run}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
    fullName: "Dr Sarah Okafor",
  }

  const signup = await request.post("/api/v1/users/signup", {
    data: {
      email: clinic.email,
      password: clinic.password,
      full_name: clinic.fullName,
      clinic_name: `Banksia Family Medical ${run}`,
    },
  })
  expect(signup.ok(), await signup.text()).toBeTruthy()

  const login = await request.post("/api/v1/login/access-token", {
    form: { username: clinic.email, password: clinic.password },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token } = await login.json()

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

  mkdirSync("playwright/.auth", { recursive: true })
  writeFileSync(CLINIC_FILE, JSON.stringify(clinic))
})
