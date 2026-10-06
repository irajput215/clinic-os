import { expect, test } from "./fixtures"

const nextWeekday = () => {
  const d = new Date()
  do d.setDate(d.getDate() + 1)
  while (d.getDay() === 0 || d.getDay() === 6)
  return d.toLocaleDateString("en-CA", { timeZone: "Australia/Sydney" })
}

test("a practitioner cannot be double-booked", async ({ signedIn: page }) => {
  const date = nextWeekday()
  await page.goto(`/calendar?date=${date}`)

  const book = async (patient: string, time: string) => {
    await page.getByRole("button", { name: "New appointment" }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByLabel("Patient").selectOption({ label: patient })
    await dialog
      .getByLabel("With")
      .selectOption({ label: "Dr James Whitfield" })
    await dialog.getByLabel("Type").selectOption("FOLLOW_UP")
    await dialog.getByLabel("Date").fill(date)
    await dialog.getByLabel("Time").fill(time)
    await dialog.getByRole("button", { name: "Book appointment" }).click()
    return dialog
  }

  await book("Grace Liu", "16:30")
  await expect(page.getByText("Booked Grace Liu at 16:30")).toBeVisible()

  const second = await book("Dean Caruso", "16:30")
  await expect(second.getByRole("alert")).toHaveText(
    "Dr James Whitfield already has Grace Liu at that time.",
  )
})

test("a public booking reaches the clinic's calendar", async ({
  signedIn: page,
}) => {
  await page.goto("/book/banksia-family-medical")
  await page.getByRole("button", { name: "Continue" }).click()

  await page.getByRole("button", { name: "Choose a time" }).click()
  await expect(
    page.getByText("Enter an Australian mobile number."),
  ).toBeVisible()

  await page
    .getByLabel("What would you like help with?")
    .fill("Chronic knee pain")
  await page.getByText("yes", { exact: true }).click()
  await page.getByLabel("Given name").fill("Nora")
  await page.getByLabel("Family name").fill("Quinn")
  await page.getByLabel("Date of birth").fill("1990-03-21")
  await page.getByLabel("Mobile").fill("0412 555 019")
  await page.getByLabel("Email").fill("nora.quinn@example.com")
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "Choose a time" }).click()

  const day = page.getByRole("button", { pressed: true }).first()
  await expect(day).toBeVisible()
  await page
    .getByRole("button", { name: /^\d\d:\d\d/ })
    .first()
    .click()
  await page.getByRole("button", { name: "Confirm booking" }).click()
  await expect(
    page.getByRole("heading", { name: "You're booked, Nora." }),
  ).toBeVisible()
  await expect(page.getByText(/BK-[A-Z0-9]{6}/)).toBeVisible()

  // The first offered slot is on the next weekday.
  await page.goto(`/calendar?view=week&date=${nextWeekday()}`)
  await expect(
    page.getByRole("button", { name: /Nora Quinn/ }).first(),
  ).toBeVisible()
})
