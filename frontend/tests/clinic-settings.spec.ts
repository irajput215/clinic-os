import { expect, openSignedIn, test } from "./fixtures"

/**
 * The clinic's display name (docs2/sdlc/01-auth-and-shell/api.md, "Clinic display name"): the
 * Practice Owner renames the clinic in Settings > Clinic, and the sidebar and the public booking
 * page show the new name. Nobody else is offered the control, and the server refuses them anyway.
 *
 * The rename uses the setup project's second clinic (`clinic.peer`), whose owner is signed in
 * already, so the shared clinic's name, which other specs read, never changes and no sign-in is
 * spent. The refusal uses the shared clinic's Doctor (`clinic.verifier`).
 */
test("the owner renames the clinic, and the sidebar and the booking page show it", async ({
  page,
  request,
  clinic,
}) => {
  const auth = { authorization: `Bearer ${clinic.peer.token}` }
  const current = await request.get("/api/v1/tenants/current", {
    headers: auth,
  })
  expect(current.ok(), await current.text()).toBeTruthy()
  const { slug } = (await current.json()) as { slug: string }

  await openSignedIn(page, clinic.peer.token, "/settings")
  await page.getByRole("tab", { name: "Clinic" }).click()
  await expect(page).toHaveURL(/tab=clinic/)

  const field = page.getByLabel("Display name")
  const save = page.getByRole("button", { name: "Save clinic name" })
  await expect(field).not.toHaveValue("")
  await expect(save).toBeDisabled()

  // Refused in the browser before anything is sent: blank once trimmed.
  await field.fill("   ")
  await save.click()
  await expect(page.getByText("Enter your clinic's name.")).toBeVisible()

  // A name this run has not used, so a retry still changes it. Spaces are tidied by the server.
  const name = `Wattle Grove Clinic ${Date.now().toString(36)}`
  await field.fill(`  ${name.replace(" Grove", "   Grove")} `)
  await save.click()
  await expect(page.getByText("Clinic name saved")).toBeVisible()
  await expect(field).toHaveValue(name)
  await expect(save).toBeDisabled()

  // The sidebar reads the same cache, so it agrees at once, and after a reload.
  await expect(page.getByTestId("sidebar-clinic")).toHaveText(name)
  await page.reload()
  await expect(page.getByTestId("sidebar-clinic")).toHaveText(name)

  // The public page shows the display name, signed out, at the unchanged link.
  const booking = await page.context().newPage()
  await booking.goto(`/book/${slug}`)
  await expect(booking.getByTestId("booking-clinic")).toHaveText(name)
  await booking.close()
})

test("someone without tenant:configure is not offered the clinic settings, and is refused", async ({
  page,
  request,
  clinic,
}) => {
  await openSignedIn(page, clinic.verifier.token, "/settings")
  await expect(
    page.getByRole("heading", { name: "Settings", level: 1 }),
  ).toBeVisible()
  // The Doctor still sees the clinic's name: it is public.
  await expect(page.getByTestId("sidebar-clinic")).not.toBeEmpty()
  await expect(page.getByRole("tab", { name: "Profile" })).toBeVisible()
  await expect(page.getByRole("tab", { name: "Clinic" })).toHaveCount(0)

  // A deep link shows the role boundary, never the form.
  await page.goto("/settings?tab=clinic")
  await expect(page.getByText("Not available to your role.")).toBeVisible()
  await expect(page.getByLabel("Display name")).toHaveCount(0)

  // The server is the boundary: the same change, sent directly, is refused.
  const refused = await request.patch("/api/v1/tenants/current/profile", {
    headers: { authorization: `Bearer ${clinic.verifier.token}` },
    data: { display_name: "Not My Clinic" },
  })
  expect(refused.status()).toBe(403)
  expect(
    ((await refused.json()) as { detail: { code: string } }).detail.code,
  ).toBe("PERMISSION_NOT_HELD")
})
