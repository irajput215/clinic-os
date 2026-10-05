import { expect, type Page, test } from "@playwright/test"

import { createUserWithClinic } from "./utils/publicApi"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser, logOutUser } from "./utils/user"

/**
 * The patients screens.
 *
 * Every test registers its own organisation: the patients API resolves the tenant from the
 * session, and an account with no organisation is refused with `403`, so a patient can only
 * be created and listed under a clinic this spec made for itself. Nothing here depends on a
 * patient that already exists.
 *
 * These tests are **unverified locally**: this sandbox cannot run the Docker stack the
 * Playwright suite needs, so CI is the first place they will actually execute.
 */

const randomSuffix = () => Math.random().toString(36).slice(2, 10)

const randomClinicName = () => `Clinic ${randomSuffix()}`

const patientNames = () => ({
  givenName: `Given${randomSuffix()}`,
  familyName: `Family${randomSuffix()}`,
})

/** Register a fresh clinic, sign in as its administrator, and land on the dashboard. */
async function registerClinicAndLogIn(page: Page) {
  const email = randomEmail()
  const password = randomPassword()
  await createUserWithClinic({
    email,
    password,
    clinicName: randomClinicName(),
  })
  await logInUser(page, email, password)
  return { email, password }
}

/** Create a patient through the UI, from the list screen. */
async function addPatient(
  page: Page,
  {
    givenName,
    familyName,
    dateOfBirth = "1980-04-02",
    suburb = "Fitzroy",
    phone = "03 9000 0000",
  }: {
    givenName: string
    familyName: string
    dateOfBirth?: string
    suburb?: string
    phone?: string
  },
) {
  await page.getByRole("button", { name: "Add patient" }).click()
  await page.getByTestId("patient-given-name-input").fill(givenName)
  await page.getByTestId("patient-family-name-input").fill(familyName)
  await page.getByTestId("patient-date-of-birth-input").fill(dateOfBirth)
  await page.getByTestId("patient-suburb-input").fill(suburb)
  await page.getByTestId("patient-phone-input").fill(phone)
  await page.getByRole("button", { name: "Save" }).click()
  await expect(page.getByText("Patient created successfully")).toBeVisible()
}

test.describe("Patients", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("creates a patient, shows it in the list and opens the record", async ({
    page,
  }) => {
    await registerClinicAndLogIn(page)
    const { givenName, familyName } = patientNames()

    await page.goto("/patients")
    await expect(
      page.getByRole("heading", { name: "Patients", level: 1 }),
    ).toBeVisible()
    // A fresh organisation has no patients: the empty state offers the same call to action.
    await expect(page.getByTestId("patients-empty")).toBeVisible()

    await addPatient(page, { givenName, familyName })

    const patientLink = page.getByRole("link", {
      name: `${familyName}, ${givenName}`,
    })
    await expect(patientLink).toBeVisible()
    // The list carries the suburb and phone the form collected.
    await expect(page.getByText("Fitzroy")).toBeVisible()
    await expect(page.getByText("03 9000 0000")).toBeVisible()

    await patientLink.click()
    await expect(page).toHaveURL(/\/patients\/[0-9a-fA-F-]{36}$/)
    await expect(
      page.getByRole("heading", {
        name: `${givenName} ${familyName}`,
        level: 1,
      }),
    ).toBeVisible()
    await expect(page.getByText("02/04/1980")).toBeVisible()
    await expect(page.getByText("Fitzroy")).toBeVisible()
    await expect(page.getByText("03 9000 0000")).toBeVisible()
    await expect(page.getByTestId("patient-not-found")).toHaveCount(0)
  })

  test("will not submit a patient without the required fields", async ({
    page,
  }) => {
    await registerClinicAndLogIn(page)
    await page.goto("/patients")

    await page.getByRole("button", { name: "Add patient" }).click()
    await page.getByRole("button", { name: "Save" }).click()

    await expect(page.getByText("Given name is required")).toBeVisible()
    await expect(page.getByText("Family name is required")).toBeVisible()
    await expect(page.getByText("Date of birth is required")).toBeVisible()
    // Validation is zod's, not the browser's: the dialog stays open and no request is made.
    await expect(page.getByRole("dialog")).toBeVisible()
  })

  test("edits an existing patient", async ({ page }) => {
    await registerClinicAndLogIn(page)
    const { givenName, familyName } = patientNames()

    await page.goto("/patients")
    await addPatient(page, { givenName, familyName })

    // The list refetches after a create, so wait for the row before opening it.
    const patientLink = page.getByRole("link", {
      name: `${familyName}, ${givenName}`,
    })
    await expect(patientLink).toBeVisible()
    await patientLink.click()
    await expect(page).toHaveURL(/\/patients\/[0-9a-fA-F-]{36}$/)
    await page.getByTestId("edit-patient-button").click()
    await page.getByTestId("patient-suburb-input").fill("Brunswick")
    await page.getByRole("button", { name: "Save changes" }).click()

    await expect(page.getByText("Patient updated successfully")).toBeVisible()
    await expect(page.getByText("Brunswick")).toBeVisible()
  })

  test("shows a not-found state, not an error, for an unknown patient", async ({
    page,
  }) => {
    await registerClinicAndLogIn(page)

    await page.goto("/patients/00000000-0000-0000-0000-000000000000")

    await expect(page.getByTestId("patient-not-found")).toBeVisible()
    await expect(
      page.getByRole("heading", { name: "Patient not found", level: 1 }),
    ).toBeVisible()
    // A 404 for a record that is not there, or is another organisation's, is not an error
    // screen and not a permission problem.
    await expect(page.getByTestId("patient-error")).toHaveCount(0)
    await expect(page.getByTestId("error-component")).toHaveCount(0)

    // An id that is not a UUID is refused by path validation (`422`) before the service
    // runs. There is still no patient to show, and the screen answers the same way.
    await page.goto("/patients/not-a-uuid")
    await expect(page.getByTestId("patient-not-found")).toBeVisible()
  })

  test("does not show another organisation's patient", async ({ page }) => {
    await registerClinicAndLogIn(page)
    const { givenName, familyName } = patientNames()

    await page.goto("/patients")
    await addPatient(page, { givenName, familyName })
    await page
      .getByRole("link", { name: `${familyName}, ${givenName}` })
      .click()
    await expect(page).toHaveURL(/\/patients\/[0-9a-fA-F-]{36}$/)
    const patientUrl = page.url()

    await logOutUser(page)
    await registerClinicAndLogIn(page)

    await page.goto(patientUrl)
    await expect(page.getByTestId("patient-not-found")).toBeVisible()
    await expect(
      page.getByRole("heading", { name: `${givenName} ${familyName}` }),
    ).toHaveCount(0)
  })
})
