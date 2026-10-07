import { type APIRequestContext, expect } from "@playwright/test"

/** Mailpit catches every email the backend sends in local and CI runs (compose.yml). */
const MAILPIT = process.env.MAILPIT_HOST ?? "http://localhost:8025"

/** The newest email Mailpit caught for `to`, as HTML. Polls: delivery is asynchronous. */
export const waitForEmailHtml = async (
  request: APIRequestContext,
  to: string,
) => {
  let html: string | undefined
  await expect
    .poll(
      async () => {
        const search = await request.get(`${MAILPIT}/api/v1/search`, {
          params: { query: `to:"${to}"`, limit: 1 },
        })
        if (!search.ok()) return false
        const { messages } = (await search.json()) as {
          messages: { ID: string }[]
        }
        if (!messages[0]) return false
        const view = await request.get(`${MAILPIT}/view/${messages[0].ID}.html`)
        html = await view.text()
        return view.ok()
      },
      { timeout: 10_000, message: `no email reached ${to}` },
    )
    .toBe(true)
  return html!
}

/**
 * The app path an emailed link points at, e.g. `/reset-password?token=...`. The backend builds the
 * link on `FRONTEND_HOST`; following only its path keeps a test independent of where that points.
 */
export const emailedPath = (html: string, path: string) => {
  const escaped = path.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")
  const link = html.match(new RegExp(`${escaped}\\?token=[^"'<\\s]+`))?.[0]
  expect(link, `${path} link in the email`).toBeTruthy()
  return link!.replace(/&amp;/g, "&")
}
