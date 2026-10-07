import { type QueryClient, queryOptions } from "@tanstack/react-query"
import { PermissionsService, RolesService, UsersService } from "@/client"
import type {
  PermissionRead,
  RoleRead,
  UserCreate,
  UserUpdate,
} from "@/client/types.gen"
import { httpStatus, refusalCode } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"

/**
 * Administration: accounts, roles, role assignment and the permission catalogue.
 *
 * Two API surfaces, with different gates, both decided by the server:
 * - roles and access (`backend/app/modules/users_roles/router.py`) need `users:manage` and an
 *   organisation; tenant comes from the session. Rate limited at 20 requests a minute per session.
 * - accounts (`backend/app/api/routes/users.py`, the frozen template layer) are platform-wide and
 *   superuser-only.
 */

/**
 * The administrative class is rate limited (20/min per session) and a view issues several reads,
 * so a `429` is retried with a wait long enough for the window to move. Every other `4xx`
 * is final; network failures and `5xx` get the app's usual retries.
 */
const retryAdmin = (failureCount: number, error: unknown) => {
  const status = httpStatus(error)
  if (status === 429) return failureCount < 3
  if (status !== undefined && status >= 400 && status < 500) return false
  return failureCount < 3
}
const retryDelay = (failureCount: number) =>
  [5_000, 20_000, 40_000][Math.min(failureCount, 2)]

const ADMIN_READ = { staleTime: 30_000, retry: retryAdmin, retryDelay }

export const rolesQuery = queryOptions({
  queryKey: ["admin", "roles"],
  queryFn: async () => (await RolesService.listRoles()).data,
  ...ADMIN_READ,
})

export const permissionCatalogueQuery = queryOptions({
  queryKey: ["admin", "permissions"],
  queryFn: async () => (await PermissionsService.listPermissions()).data,
  ...ADMIN_READ,
})

export const userRolesQuery = (userId: string) =>
  queryOptions({
    queryKey: ["admin", "user-roles", userId],
    queryFn: async () =>
      (await UsersService.readUserRoles({ path: { user_id: userId } })).data,
    ...ADMIN_READ,
  })

export const userPermissionsQuery = (userId: string) =>
  queryOptions({
    queryKey: ["admin", "user-permissions", userId],
    queryFn: async () =>
      (await UsersService.readUserPermissions({ path: { user_id: userId } }))
        .data,
    ...ADMIN_READ,
  })

export const ACCOUNTS_PAGE_SIZE = 50

export const accountsQuery = (page: number) =>
  queryOptions({
    queryKey: ["admin", "accounts", page],
    queryFn: async () =>
      (
        await UsersService.readUsers({
          query: { skip: page * ACCOUNTS_PAGE_SIZE, limit: ACCOUNTS_PAGE_SIZE },
        })
      ).data,
    staleTime: 30_000,
  })

export const assignRole = async (userId: string, roleId: string) =>
  (
    await UsersService.assignRole({
      path: { user_id: userId },
      body: { role_id: roleId },
    })
  ).data

export const revokeRole = async (userId: string, roleId: string) => {
  await UsersService.revokeRole({
    path: { user_id: userId, role_id: roleId },
  })
}

export const createAccount = async (body: UserCreate) =>
  (await UsersService.createUser({ body })).data

export const updateAccount = async (userId: string, body: UserUpdate) =>
  (await UsersService.updateUser({ path: { user_id: userId }, body })).data

export const deactivateAccount = async (userId: string) =>
  (await UsersService.deleteUser({ path: { user_id: userId } })).data

/**
 * A write is retried only after a `429`: the rate limit refuses before the request runs, so sending
 * it again cannot apply it twice. Every other failure is the server's answer and is shown.
 */
export const ADMIN_WRITE = {
  retry: (failureCount: number, error: unknown) =>
    httpStatus(error) === 429 && failureCount < 3,
  retryDelay,
}

export type AccessChange =
  | { kind: "granted"; role: RoleRead }
  | { kind: "revoked"; roleId: string }
  | { kind: "unknown" }

/**
 * After a grant or revoke. The server's answer already says what changed in the assignment list,
 * so that is applied directly; the effective set (computed server-side) is refetched, as is the
 * signed-in user's own set when it was their account. Nothing else is refetched: these reads share
 * the 20-a-minute administrative budget. Not awaited by callers, so a rate-limited refetch never
 * holds up the confirmation.
 */
export function applyAccessChange(
  queryClient: QueryClient,
  userId: string,
  change: AccessChange,
) {
  const rolesKey = userRolesQuery(userId).queryKey
  if (change.kind === "unknown")
    void queryClient.invalidateQueries({ queryKey: rolesKey })
  else
    queryClient.setQueryData(rolesKey, (list) => {
      if (!list) return list
      const data =
        change.kind === "granted"
          ? list.data.some((a) => a.role_id === change.role.id)
            ? list.data
            : [
                ...list.data,
                {
                  role_id: change.role.id,
                  code: change.role.code,
                  name: change.role.name,
                  is_system: change.role.is_system,
                  granted_at: new Date().toISOString(),
                },
              ]
          : list.data.filter((a) => a.role_id !== change.roleId)
      return { data, count: data.length }
    })
  void queryClient.invalidateQueries({
    queryKey: userPermissionsQuery(userId).queryKey,
  })
  if (queryClient.getQueryData(currentUserQuery.queryKey)?.id === userId)
    void queryClient.invalidateQueries({ queryKey: ["session", "permissions"] })
}

// --- Presentation of the catalogue -----------------------------------------------------------

export interface PermissionGroup {
  id: string
  title: string
  permissions: PermissionRead[]
}

/**
 * How the catalogue is grouped for reading. Presentation only: the codes and descriptions come
 * from `GET /permissions`, and a code no group names is kept under "Other", never dropped.
 * MIRROR: backend/app/modules/users_roles/catalog.py (21 codes).
 */
const GROUPS: ReadonlyArray<{ id: string; title: string; codes: string[] }> = [
  {
    id: "patients",
    title: "Patients",
    codes: [
      "patient:read",
      "patient:create",
      "patient:update",
      "patient:export",
    ],
  },
  {
    id: "clinical-records",
    title: "Clinical records",
    codes: ["clinical_record:read", "clinical_record:write"],
  },
  {
    id: "prescriptions",
    title: "Prescriptions",
    codes: [
      "prescription:create",
      "prescription:modify",
      "prescription:sign",
      "prescription:dispatch",
    ],
  },
  {
    id: "tga",
    title: "TGA approvals",
    codes: [
      "tga_approval:read",
      "tga_approval:create",
      "tga_approval:verify",
      "tga_approval:revoke",
      "tga_inbox:process",
    ],
  },
  { id: "pharmacy", title: "Pharmacy", codes: ["pharmacy:dispatch"] },
  {
    id: "oversight",
    title: "Oversight",
    codes: ["audit:read", "reports:export"],
  },
  {
    id: "organisation",
    title: "Organisation",
    codes: ["users:manage", "tenant:configure", "tenant:read"],
  },
]

export function groupPermissions(
  permissions: readonly PermissionRead[],
): PermissionGroup[] {
  const byCode = new Map(permissions.map((p) => [p.code, p]))
  const placed = new Set<string>()
  const groups: PermissionGroup[] = []
  for (const group of GROUPS) {
    const items = group.codes.flatMap((code) => {
      const p = byCode.get(code)
      if (!p) return []
      placed.add(code)
      return [p]
    })
    if (items.length) groups.push({ ...group, permissions: items })
  }
  const other = permissions.filter((p) => !placed.has(p.code))
  if (other.length)
    groups.push({ id: "other", title: "Other", permissions: other })
  return groups
}

/**
 * R3, read in advance: a role is grantable when the caller already holds every permission in its
 * bundle. Advisory only; the server recomputes it and answers `403 GRANT_EXCEEDS_ACTOR`.
 * `undefined` when the caller's own set isn't known.
 */
export function missingToGrant(
  role: Pick<RoleRead, "permissions">,
  held: readonly string[] | undefined,
): string[] | undefined {
  if (!held) return undefined
  const set = new Set(held)
  return role.permissions
    .map((p) => p.code)
    .filter((code) => !set.has(code))
    .sort()
}

export const GRANT_RULE =
  "You can grant only roles whose permissions you already hold."

/** One sentence for a refused grant or revoke, using the API's machine code where it has one. */
export function describeAccessError(error: unknown): string | undefined {
  const code = refusalCode(error)
  if (code === "GRANT_EXCEEDS_ACTOR")
    return "The server refused this grant: the role includes permissions your own roles don't. Ask someone who holds them to grant it."
  if (code === "LAST_ADMINISTRATOR")
    return "This is the organisation's last account that can manage users. Give another account an administrator role before revoking this one."
  return undefined
}

/** "a, b and c" */
export function formatList(items: readonly string[]): string {
  if (items.length <= 1) return items.join("")
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`
}
