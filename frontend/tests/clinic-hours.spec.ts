import { randomBytes } from "node:crypto"
import { signInWithApi, signUp } from "./accounts"
import { expect, openSignedIn, test } from "./fixtures"
import { waitForEmailHtml } from "./mail"

/**
 * Clinic hours, slot length and booking emails (docs2/sdlc/04-calendar-and-booking R8, R9).
 *
 * The owner of a clinic of its own (one signup, one sign-in): changing the hours of the shared
 * clinic would change the slots every other booking spec reads. The owner also takes the Doctor
 * role, so the clinic has someone to book with. The refusal uses the shared clinic's Doctor.
 */
const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const

/** The Sydney weekday two days from now: always inside the booking page's 14 days, twice. */
const openWeekday = () => {
  const today = new Date().toLocaleDateString("en-CA", {
    timeZone: "Australia/Sydney",
  })
  const d = new Date(`${today}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 2)
  return WEEKDAYS[(d.getUTCDay() + 6) % 7]
}

test("the owner sets the hours and slot length, and the booking page offers exactly those slots; a booking is emailed", async ({
  page,
  request,
}) => {
  test.setTimeout(90_000)
  const owner = await signUp(request, { clinic: true })
  const token = await signInWithApi(request, owner)
  const auth = { authorization: `Bearer ${token}` }
  const roles = await request.get("/api/v1/roles", { headers: auth })
  const doctor = (
    (await roles.json()) as { data: { id: string; code: string }[] }
  ).data.find((role) => role.code === "DOCTOR")
  const me = await request.get("/api/v1/users/me", { headers: auth })
  const { id: ownerId } = (await me.json()) as { id: string }
  const granted = await request.post(`/api/v1/users/${ownerId}/roles`, {
    headers: auth,
    data: { role_id: doctor?.id },
  })
  expect(granted.ok(), await granted.text()).toBeTruthy()
  const current = await request.get("/api/v1/tenants/current", {
    headers: auth,
  })
  const { slug } = (await current.json()) as { slug: string }

  await openSignedIn(page, token, "/settings?tab=clinic")
  const card = page.getByRole("region", { name: "Opening hours" })
  const save = card.getByRole("button", { name: "Save opening hours" })
  await expect(save).toBeDisabled()

  const open = openWeekday()
  for (const day of WEEKDAYS) {
    const box = card.getByLabel(`Open on ${day}`)
    if (day === open) await box.check()
    else await box.uncheck()
  }
  // Refused in the browser first: closing before opening, named on the day.
  await card.getByLabel(`${open} opens`).fill("11:00")
  await card.getByLabel(`${open} closes`).fill("10:00")
  await save.click()
  await expect(card.getByText("Closing must be after opening.")).toBeVisible()

  await card.getByLabel(`${open} opens`).fill("10:00")
  await card.getByLabel(`${open} closes`).fill("11:00")
  await card.getByLabel("Slot length").selectOption({ label: "30 minutes" })
  await save.click()
  await expect(page.getByText("Opening hours saved")).toBeVisible()
  await expect(save).toBeDisabled()

  // The public page, signed out, offers a 30-minute consult at 10:00 and 10:30 on that day only.
  const booking = await page.context().newPage()
  await booking.goto(`/book/${slug}`)
  await booking.getByRole("button", { name: /Initial doctor consult/ }).click()
  await booking.getByRole("button", { name: "Continue" }).click()
  await booking
    .getByLabel("What would you like help with?")
    .fill("Chronic knee pain")
  await booking.getByText("yes", { exact: true }).click()
  await booking.getByLabel("Given name").fill("Nora")
  await booking.getByLabel("Family name").fill("Quinn")
  await booking.getByLabel("Date of birth").fill("1990-03-21")
  await booking.getByLabel("Mobile").fill("0412 555 019")
  const email = `hours-${randomBytes(4).toString("hex")}@example.com`
  await booking.getByLabel("Email").fill(email)
  await booking.getByRole("checkbox").check()
  await booking.getByRole("button", { name: "Choose a time" }).click()

  const days = booking.getByRole("button", { pressed: true }).first()
  await expect(days).toContainText(open.slice(0, 3), { ignoreCase: true })
  const times = booking.getByRole("button", { name: /^\d\d:\d\d/ })
  await expect(times).toHaveCount(2)
  await expect(times.nth(0)).toHaveText(/^10:00/)
  await expect(times.nth(1)).toHaveText(/^10:30/)

  await times.nth(1).click()
  await booking.getByRole("button", { name: "Confirm booking" }).click()
  await expect(
    booking.getByRole("heading", { name: "You're booked, Nora." }),
  ).toBeVisible()
  const reference = (await booking
    .getByText(/BK-[A-Z0-9]{6}/)
    .first()
    .textContent())!.match(/BK-[A-Z0-9]{6}/)![0]

  // The confirmation email: the clinic, the time and the reference, and nothing clinical.
  const html = await waitForEmailHtml(request, email)
  expect(html).toContain(reference)
  expect(html).toContain("10:30 am (Sydney time)")
  expect(html).toContain("Wattle Clinic")
  for (const withheld of ["Nora", "Quinn", "knee", "consult", "0412"])
    expect(html, withheld).not.toContain(withheld)
})

test("someone without tenant:configure cannot change the hours", async ({
  page,
  request,
  clinic,
}) => {
  await openSignedIn(page, clinic.verifier.token, "/settings?tab=clinic")
  await expect(page.getByText("Not available to your role.")).toBeVisible()
  await expect(page.getByRole("region", { name: "Opening hours" })).toHaveCount(
    0,
  )
  const refused = await request.put("/api/v1/appointment-settings", {
    headers: { authorization: `Bearer ${clinic.verifier.token}` },
    data: {
      slot_minutes: 15,
      hours: WEEKDAYS.map((_, i) => ({
        weekday: i + 1,
        opens_at: "09:00",
        closes_at: "10:00",
      })),
    },
  })
  expect(refused.status()).toBe(403)
})
