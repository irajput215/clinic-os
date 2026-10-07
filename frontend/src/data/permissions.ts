import { queryOptions, useQuery } from "@tanstack/react-query"
import { UsersService } from "@/client"
import { httpStatus } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"

/**
 * The signed-in account's own effective permission codes: `GET /users/me/permissions` ->
 * `{ permissions: string[] }` (docs2/sdlc/01-auth-and-shell/api.md; the self-permissions row of
 * docs/features/03-users-and-roles/03-design.md). A `404` or `422` can only come from a backend that
 * predates the route (it then falls through to `/users/{user_id}/permissions`): the set is "unknown"
 * and the UI shows its controls, relying on the server's `403`. This only hides and explains; the
 * backend decides every request.
 */
export type MyPermissions =
  | { known: true; codes: readonly string[] }
  | { known: false }

export const myPermissionsQuery = queryOptions({
  queryKey: ["session", "permissions"],
  queryFn: async (): Promise<MyPermissions> => {
    try {
      const { data } = await UsersService.readOwnPermissions()
      return { known: true, codes: data.permissions }
    } catch (error) {
      const status = httpStatus(error)
      if (status === 404 || status === 422) return { known: false }
      // `403` is the answer for an account with no organisation: it holds nothing.
      if (status === 403) return { known: true, codes: [] }
      throw error
    }
  },
  staleTime: 5 * 60_000,
})

/** The permission that opens the roles and access administration. */
export const MANAGE_USERS = "users:manage"

/**
 * Whether to offer the administration area: a platform superuser (accounts), or anyone whose known
 * set includes `users:manage`. An account with no organisation can hold no permission. When the set
 * is unknown or failed to load, the entry is shown and the server's `403` is the answer.
 */
export function useCanAdminister(): boolean {
  const me = useQuery(currentUserQuery)
  // Asked only when the answer can change what is shown.
  const permissions = useQuery({
    ...myPermissionsQuery,
    retry: false,
    enabled: Boolean(me.data?.tenant_id) && !me.data?.is_superuser,
  })
  if (me.data?.is_superuser) return true
  if (!me.data?.tenant_id) return false
  // Not shown until the answer is in, so the entry never appears and then vanishes.
  if (permissions.isPending) return false
  if (permissions.data?.known)
    return permissions.data.codes.includes(MANAGE_USERS)
  return true
}
