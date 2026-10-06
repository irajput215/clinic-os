import { queryOptions } from "@tanstack/react-query"
import { LoginService, UsersService } from "@/client"
import type { UserPublic } from "@/client/types.gen"

/**
 * The access token lives in `sessionStorage`: one browser tab, gone when the tab closes, never
 * shared with another tab or a later visit. Rationale and the httpOnly-cookie target are in
 * docs2/adr/ADR-F002-token-storage.md. The token is short-lived (15 minutes, server-enforced), and the
 * server re-validates it on every request, so nothing here is a security decision.
 */
const TOKEN_KEY = "clinic-os.access_token"

const storage = (): Storage | undefined => {
  try {
    return window.sessionStorage
  } catch {
    return undefined
  }
}

export const readToken = (): string | null => {
  try {
    return storage()?.getItem(TOKEN_KEY) ?? null
  } catch {
    return null
  }
}

const writeToken = (token: string | null) => {
  try {
    if (token) storage()?.setItem(TOKEN_KEY, token)
    else storage()?.removeItem(TOKEN_KEY)
  } catch {
    // Storage blocked (private mode, policy): the session simply won't survive a reload.
  }
}

export const isSignedIn = (): boolean => readToken() !== null

export const signIn = async (username: string, password: string) => {
  const { data } = await LoginService.loginAccessToken({
    body: { username, password },
  })
  writeToken(data.access_token)
}

export const signOut = () => {
  writeToken(null)
}

export const currentUserQuery = queryOptions({
  queryKey: ["session", "me"],
  queryFn: async (): Promise<UserPublic> =>
    (await UsersService.readUserMe()).data,
  staleTime: 5 * 60_000,
})

/** Display name: the account's full name, else the part of the email before the `@`. */
export const displayName = (user: Pick<UserPublic, "full_name" | "email">) =>
  user.full_name?.trim() || user.email.split("@")[0]
