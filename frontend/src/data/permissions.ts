import { queryOptions } from "@tanstack/react-query"
import { UsersService } from "@/client"
import { httpStatus } from "@/lib/http"

/**
 * The signed-in account's own effective permission codes: `GET /users/me/permissions` ->
 * `{ permissions: string[] }` (docs2/sdlc/01-auth-and-shell/api.md; the self-permissions row of
 * docs/features/03-users-and-roles/03-design.md). A `404` or `422` can only come from a backend that
 * predates the route (it then falls through to `/users/{user_id}/permissions`): the set is "unknown"
 * and the UI shows its controls, relying on the server's `403`. This only hides and explains; the
 * backend decides every request.
 */
export type MyPermissions =
  | {
      known: true
      codes: readonly string[]
      /** Held only through a care relationship (a doctor's or nurse's patient grants, T1-34). */
      relationshipBound: readonly string[]
      /** The account's own role codes (docs3 feature 02: the "first hour" card). */
      roleCodes: readonly string[]
    }
  | { known: false }

export const myPermissionsQuery = queryOptions({
  queryKey: ["session", "permissions"],
  queryFn: async (): Promise<MyPermissions> => {
    try {
      const { data } = await UsersService.readOwnPermissions()
      return {
        known: true,
        codes: data.permissions,
        relationshipBound: data.relationship_bound ?? [],
        roleCodes: data.role_codes ?? [],
      }
    } catch (error) {
      const status = httpStatus(error)
      if (status === 404 || status === 422) return { known: false }
      // `403` is the answer for an account with no organisation: it holds nothing.
      if (status === 403)
        return { known: true, codes: [], relationshipBound: [], roleCodes: [] }
      throw error
    }
  },
  staleTime: 5 * 60_000,
})

/** The permission that opens the roles and access administration. */
export const MANAGE_USERS = "users:manage"
