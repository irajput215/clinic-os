import type { Page } from "@playwright/test"

/**
 * The six-step online application (docs3/03-patient-intake), filled the shortest valid way: every
 * safety answer "No", every consent ticked, the patient's own pharmacy, signed in their own name.
 * Starts on step 1 ("About you") and leaves the page on the time picker.
 */
export async function fillApplication(
  page: Page,
  person: { given: string; family: string; email: string },
) {
  await page.getByLabel("Given name").fill(person.given)
  await page.getByLabel("Family name").fill(person.family)
  await page.getByLabel("Date of birth").fill("1990-03-21")
  await page.getByLabel("Sex").selectOption("FEMALE")
  await page.getByLabel("Mobile").fill("0412 555 019")
  await page.getByLabel("Email").fill(person.email)
  await page.getByLabel("Street address").fill("14 Vulture St")
  await page.getByLabel("Suburb").fill("West End")
  await page.getByLabel("State").selectOption("QLD")
  await page.getByLabel("Postcode").fill("4101")
  await page.getByRole("button", { name: "Continue" }).click()

  await page
    .getByLabel("What would you like help with?")
    .selectOption("CHRONIC_PAIN")
  for (const group of await page.getByRole("group").all())
    await group.getByText("No", { exact: true }).click()
  await page.getByRole("button", { name: "Continue" }).click()

  await page.getByText("No", { exact: true }).click()
  await page.getByRole("button", { name: "Continue" }).click()

  for (const box of await page.getByRole("checkbox").all()) await box.check()
  await page.getByRole("button", { name: "Continue" }).click()

  await page.getByLabel("My own pharmacy").check()
  await page.getByLabel("Pharmacy name").fill("Corner Pharmacy")
  await page.getByLabel("Suburb").fill("West End")
  await page.getByLabel("Address").fill("1 Boundary St")
  await page.getByLabel("Email").fill("orders@corner.example.com")
  await page.getByLabel("Phone").fill("07 3000 0000")
  await page.getByRole("button", { name: "Continue" }).click()

  await page
    .getByLabel("Type your full name to sign")
    .fill(`${person.given} ${person.family}`)
  await page.getByRole("button", { name: "Choose a time" }).click()
}
