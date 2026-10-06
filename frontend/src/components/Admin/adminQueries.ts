/**
 * The query and mutation options the administration screen uses.
 *
 * A `403` from this API — a caller who is signed in but does not hold `users:manage`, or an
 * account with no organisation — stays in the page and renders as the screen's own
 * permission-denied state. That is now the rule for every request (`main.tsx` signs out on
 * `401` only), so nothing here opts out of anything: the screen shows what the API answered.
 *
 * Retrying is limited to `429`. The administrative class is rate limited at 20 requests a
 * minute per client address, and this screen issues several requests per view, so a few
 * quick reloads can reach it. A `403`, `404` or `422` is a final answer and is never
 * retried; anything else gets a "Try again" control.
 */

import { PermissionsService, RolesService, UsersService } from "@/client"
import { retryDelayMs, retryOnRateLimit } from "@/lib/admin"

/**
 * The screen issues several requests per view and the administrative class is limited to
 * 20 a minute per client address, so a tab switch must not refetch what the cache already
 * holds. `staleTime` makes a remount within the window free; a mutation still invalidates
 * the keys it changed.
 */
const ADMIN_QUERY_CACHE = { staleTime: 30_000 }

const RETRY_ON_RATE_LIMIT = {
  retry: retryOnRateLimit,
  retryDelay: retryDelayMs,
}

/** `GET /roles` — the organisation's roles with their permission bundles. */
export const rolesQueryOptions = {
  queryKey: ["admin", "roles"],
  queryFn: async () => (await RolesService.listRoles()).data,
  ...ADMIN_QUERY_CACHE,
  ...RETRY_ON_RATE_LIMIT,
}

/** `GET /permissions` — the global permission catalogue, read-only reference data. */
export const permissionsQueryOptions = {
  queryKey: ["admin", "permissions"],
  queryFn: async () => (await PermissionsService.listPermissions()).data,
  ...ADMIN_QUERY_CACHE,
  ...RETRY_ON_RATE_LIMIT,
}

/** `GET /users/{id}/roles` — the roles one account holds in the caller's organisation. */
export const userRolesQueryOptions = (userId: string) => ({
  queryKey: ["admin", "user-roles", userId],
  queryFn: async () =>
    (await UsersService.readUserRoles({ path: { user_id: userId } })).data,
  enabled: userId.length > 0,
  ...ADMIN_QUERY_CACHE,
  ...RETRY_ON_RATE_LIMIT,
})

/** `GET /users/{id}/permissions` — one account's effective set, computed server-side. */
export const userPermissionsQueryOptions = (userId: string) => ({
  queryKey: ["admin", "user-permissions", userId],
  queryFn: async () =>
    (await UsersService.readUserPermissions({ path: { user_id: userId } }))
      .data,
  enabled: userId.length > 0,
  ...ADMIN_QUERY_CACHE,
  ...RETRY_ON_RATE_LIMIT,
})

/** The signed-in user's own effective set, which is what grantability is read from (R3). */
export const selfPermissionsQueryOptions = (userId: string | undefined) =>
  userPermissionsQueryOptions(userId ?? "")
