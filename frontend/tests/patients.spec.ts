import { expect, openSignedIn, test } from "./fixtures"

test("the patients list shows the clinic's patients and searches the API", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await expect(page.getByRole("cell", { name: "Marcus Webb" })).toBeVisible()

  // The search is server-side and the term never enters a URL.
  const searches: string[] = []
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/patients")) searches.push(request.url())
  })
  await page.getByLabel("Search patients").fill("caru")
  await expect(page.getByRole("cell", { name: "Dean Caruso" })).toBeVisible()
  await expect(page.getByRole("cell", { name: "Marcus Webb" })).toBeHidden()
  await expect(page.getByText("1 match", { exact: true })).toBeVisible()
  expect(searches.some((url) => url.endsWith("/api/v1/patients/search"))).toBe(
    true,
  )
  expect(searches.every((url) => !url.toLowerCase().includes("caru"))).toBe(
    true,
  )
  expect(page.url()).not.toContain("caru")

  // A date of birth in the Australian order finds the patient too.
  await page.getByLabel("Search patients").fill("22/01/1968")
  await expect(page.getByRole("cell", { name: "Dean Caruso" })).toBeVisible()

  await page.getByLabel("Search patients").fill("nobody-by-this-name")
  await expect(page.getByText("No patients match that search.")).toBeVisible()
})

test("every patient is reachable: the list loads more past the first page", async ({
  page,
  request,
  clinic,
}) => {
  // The second clinic, so the shared clinic's six patients stay as other specs expect them.
  const auth = { authorization: `Bearer ${clinic.peer.token}` }
  const listed = await request.get("/api/v1/patients?limit=1", {
    headers: auth,
  })
  expect(listed.status()).toBe(200)
  const existing = (await listed.json()).count as number
  for (let i = existing; i < 27; i++) {
    const created = await request.post("/api/v1/patients", {
      headers: auth,
      data: {
        given_name: "Page",
        family_name: `Zentner${String(i).padStart(2, "0")}`,
        date_of_birth: "1990-01-01",
      },
    })
    expect(created.status(), await created.text()).toBe(201)
  }

  await openSignedIn(page, clinic.peer.token, "/patients")
  await expect(page.getByText("Showing 25 of 27")).toBeVisible()
  await expect(page.getByRole("cell", { name: "Page Zentner26" })).toBeHidden()

  await page.getByRole("button", { name: "Load more" }).click()
  await expect(page.getByText("Showing 27 of 27")).toBeVisible()
  await expect(page.getByRole("cell", { name: "Page Zentner26" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Load more" })).toBeHidden()

  // The top-bar quick-find reaches a patient beyond the first page too.
  await page.getByRole("combobox", { name: "Find a patient" }).fill("zentner26")
  await page.getByRole("option", { name: /Page Zentner26/ }).click()
  await expect(page).toHaveURL(/\/patients\/[0-9a-f-]{36}$/)
  await expect(
    page.getByRole("heading", { name: "Page Zentner26" }),
  ).toBeVisible()
})

test("a patient is added through the API and opens on their record", async ({
  signedIn: page,
}) => {
  await page.goto("/patients")
  await page.getByRole("button", { name: "Add patient" }).first().click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(dialog.getByText("Enter a given name.")).toBeVisible()

  await dialog.getByLabel("Given name").fill("Luke")
  await dialog.getByLabel("Family name").fill("Lawson")
  await dialog.getByLabel("Date of birth").fill("1988-05-14")
  await dialog.getByLabel("Postcode").fill("30")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(dialog.getByText("Use a 4-digit postcode.")).toBeVisible()

  await dialog.getByLabel("Postcode").fill("3066")
  await dialog.getByRole("button", { name: "Add patient" }).click()
  await expect(page).toHaveURL(/\/patients\/[0-9a-f-]{36}$/)
  await expect(page.getByRole("heading", { name: "Luke Lawson" })).toBeVisible()

  // The create is in the real, hash-chained audit trail.
  await page.getByRole("tab", { name: "Activity" }).click()
  await expect(page.getByRole("cell", { name: "Patient create" })).toBeVisible()
})

test("an unknown patient id is a not-found page, not an error", async ({
  signedIn: page,
}) => {
  await page.goto("/patients/00000000-0000-4000-8000-000000000000")
  await expect(
    page.getByText("That patient record isn't available."),
  ).toBeVisible()
})
