import { randomBytes, randomInt } from "node:crypto"
import { expect, test } from "./fixtures"

/**
 * Calendar and public booking against the real appointments module. The setup project grants the
 * clinic's owner (Dr Sarah Okafor) the Doctor role, so she is the clinic's one bookable practitioner.
 */
const sydneyDate = (d: Date) =>
  d.toLocaleDateString("en-CA", { timeZone: "Australia/Sydney" })

/** A weekday far enough ahead, and random, so a retry never meets its own earlier booking. */
const someWeekday = () => {
  const d = new Date()
  d.setDate(d.getDate() + randomInt(30, 900))
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
  return sydneyDate(d)
}

test("a practitioner cannot be double-booked, and a booking moves through its states", async ({
  signedIn: page,
}) => {
  const date = someWeekday()
  await page.goto(`/calendar?date=${date}`)
  await expect(page.getByText("Dr Sarah Okafor").first()).toBeVisible()
  await expect(page.getByText("Preview data")).toHaveCount(0)

  const book = async (patient: string, time: string) => {
    await page.getByRole("button", { name: "New appointment" }).click()
    const dialog = page.getByRole("dialog")
    await dialog.getByLabel("Patient").selectOption({ label: patient })
    await dialog.getByLabel("With").selectOption({ label: "Dr Sarah Okafor" })
    await dialog.getByLabel("Type").selectOption("FOLLOW_UP")
    await dialog.getByLabel("Date").fill(date)
    await dialog.getByLabel("Time").fill(time)
    await dialog.getByRole("button", { name: "Book appointment" }).click()
    return dialog
  }

  await book("Grace Liu", "16:30")
  await expect(page.getByText("Booked Grace Liu at 16:30")).toBeVisible()

  // The refusal comes from the database's exclusion constraint, and names the clash's time, never
  // the other patient.
  const second = await book("Dean Caruso", "16:30")
  await expect(second.getByRole("alert")).toHaveText(
    "Dr Sarah Okafor is already booked from 16:30 to 16:45.",
  )
  await second.getByRole("button", { name: "Cancel" }).click()

  // The booking is real: it survives a reload, and its status moves on the server.
  await page.reload()
  await page.getByRole("button", { name: /Grace Liu/ }).click()
  const details = page.getByRole("dialog", { name: "Grace Liu" })
  await details.getByRole("button", { name: "Confirm" }).click()
  await expect(page.getByText("Grace Liu: confirmed")).toBeVisible()
  await page.reload()
  await page.getByRole("button", { name: /Grace Liu/ }).click()
  await expect(
    page.getByRole("dialog", { name: "Grace Liu" }).getByText("Confirmed"),
  ).toBeVisible()
})

test("a public booking reaches the clinic's calendar", async ({
  signedIn: page,
  clinic,
  request,
}) => {
  const slots = await request.get(
    `/api/v1/public/${clinic.slug}/slots?type=INITIAL_CONSULT`,
  )
  expect(slots.ok(), await slots.text()).toBeTruthy()
  const [first] = (await slots.json()) as { starts_at: string }[]
  const firstDay = sydneyDate(new Date(first.starts_at))

  await page.goto(`/book/${clinic.slug}`)
  // The page names the clinic from its slug: the only public identity a clinic has.
  await expect(page.getByText(/^Ironbark Medical [0-9a-f]{8}$/i)).toBeVisible()
  await expect(page.getByText("Preview data")).toHaveCount(0)
  await page.getByRole("button", { name: /Initial doctor consult/ }).click()
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
  await page
    .getByLabel("Email")
    .fill(`nora-${randomBytes(4).toString("hex")}@example.com`)
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "Choose a time" }).click()

  await expect(
    page.getByRole("button", { pressed: true }).first(),
  ).toBeVisible()
  await page
    .getByRole("button", { name: /^\d\d:\d\d/ })
    .first()
    .click()
  await page.getByRole("button", { name: "Confirm booking" }).click()
  await expect(
    page.getByRole("heading", { name: "You're booked, Nora." }),
  ).toBeVisible()
  await expect(page.getByText(/BK-[A-Z0-9]{6}/)).toBeVisible()

  // The first offered time, on the clinic's real calendar, marked as from the booking page.
  await page.goto(`/calendar?view=week&date=${firstDay}`)
  await page
    .getByRole("button", { name: /Nora Quinn/ })
    .first()
    .click()
  await expect(
    page
      .getByRole("dialog", { name: "Nora Quinn" })
      .getByText("Public booking page", { exact: true }),
  ).toBeVisible()
})

test("an unknown clinic's booking page says so", async ({ page }) => {
  await page.goto(`/book/no-such-clinic-${randomBytes(4).toString("hex")}`)
  await expect(
    page.getByRole("heading", { name: "This booking page isn't available" }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0)
})
