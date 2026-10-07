import { randomBytes } from "node:crypto"
import { existsSync, readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { type APIRequestContext, expect, type Page } from "@playwright/test"

export interface Account {
  email: string
  password: string
  fullName: string
}

const run = () => randomBytes(4).toString("hex")

/**
 * A fresh account of its own, so a test that changes a password, a name or a role never touches the
 * shared clinic other specs sign in as. `clinic: true` registers an organisation and makes the
 * account its practice owner; `clinic: false` is an account that belongs to no organisation.
 */
export async function signUp(
  request: APIRequestContext,
  { clinic }: { clinic: boolean },
): Promise<Account> {
  const id = run()
  const account: Account = {
    email: `${clinic ? "owner" : "staff"}-${id}@e2e.example.com`,
    password: `E2e-${randomBytes(9).toString("base64url")}`,
    fullName: clinic ? "Dr Ana Petrovic" : "Sam Reyes",
  }
  const res = await request.post("/api/v1/users/signup", {
    data: {
      email: account.email,
      password: account.password,
      full_name: account.fullName,
      ...(clinic ? { clinic_name: `Wattle Clinic ${id}` } : {}),
    },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return account
}

/** Sign in through the real sign-in page, as a person would. */
export async function signInThroughUi(
  page: Page,
  { email, password }: Pick<Account, "email" | "password">,
  to = "/",
) {
  await page.goto(`/login?redirect=${encodeURIComponent(to)}`)
  await page.getByLabel("Email").fill(email)
  await page.getByLabel("Password").fill(password)
  await page.getByRole("button", { name: "Sign in" }).click()
  await expect(page).toHaveURL((url) => url.pathname === to)
}

/**
 * The platform superuser the backend seeds from FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD. Read
 * from the environment, else from the repository's untracked `.env` (CI copies `.env.example`), so
 * no credential is written into the suite.
 */
export function superuser(): Pick<Account, "email" | "password"> {
  const fromFile: Record<string, string> = {}
  const path = fileURLToPath(new URL("../../.env", import.meta.url))
  if (existsSync(path))
    for (const line of readFileSync(path, "utf8").split("\n")) {
      const match = /^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/.exec(line)
      if (match) fromFile[match[1]] = match[2].replace(/^(['"])(.*)\1$/, "$2")
    }
  const email = process.env.FIRST_SUPERUSER ?? fromFile.FIRST_SUPERUSER
  const password =
    process.env.FIRST_SUPERUSER_PASSWORD ?? fromFile.FIRST_SUPERUSER_PASSWORD
  if (!email || !password)
    throw new Error(
      "FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD must be set (env or repository .env)",
    )
  return { email, password }
}

/**
 * An access token for `account`, signed in through the API. It spends one of the run's sign-ins
 * (see `fixtures.ts`), so it is for a fresh account a test needs a session as, never a stand-in for
 * the sign-in page.
 */
export async function signInWithApi(
  request: APIRequestContext,
  { email, password }: Pick<Account, "email" | "password">,
): Promise<string> {
  const login = await request.post("/api/v1/login/access-token", {
    form: { username: email, password },
  })
  expect(login.ok(), await login.text()).toBeTruthy()
  return ((await login.json()) as { access_token: string }).access_token
}
