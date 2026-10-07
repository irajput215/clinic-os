import { queryOptions, useQuery } from "@tanstack/react-query"
import { TenantsService } from "@/client"
import { httpStatus } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"
import { myPermissionsQuery } from "./permissions"

/**
 * The signed-in account's own organisation, `GET /api/v1/tenants/current`. The tenant comes from the
 * session on the server; nothing here names one.
 *
 * Only the routing `slug` identifies the clinic to the app. Its display name (`legal_name`) is not
 * readable by the application's database role, so the API never returns it and the app never shows
 * a name it does not have. The route needs `tenant:read` (Practice Owner and Compliance / Auditor);
 * anyone else is refused `403`, and the app then shows no clinic identity at all.
 *
 * The route is in the administrative rate-limit class (20/min per client address), so a `429` waits
 * for the window to move; every other `4xx` is final. The slug cannot change during a session.
 */
export const TENANT_READ = "tenant:read"

export const currentTenantQuery = queryOptions({
  queryKey: ["session", "tenant"],
  queryFn: async () => (await TenantsService.readCurrentTenant()).data,
  staleTime: Number.POSITIVE_INFINITY,
  retry: (failureCount, error) => {
    const status = httpStatus(error)
    if (status === 429) return failureCount < 3
    if (status !== undefined && status >= 400 && status < 500) return false
    return failureCount < 3
  },
  retryDelay: (failureCount) =>
    [5_000, 20_000, 40_000][Math.min(failureCount, 2)],
})

/**
 * The signed-in clinic's slug, or `undefined` while it is unknown: loading, refused, or an account
 * with no organisation. Not asked when the account's known permissions already rule it out, so the
 * request is never one the server is certain to refuse.
 */
export function useClinicSlug(): string | undefined {
  const me = useQuery(currentUserQuery)
  const inOrganisation = Boolean(me.data?.tenant_id)
  const superuser = Boolean(me.data?.is_superuser)
  // The same query `useCanAdminister` makes; a platform superuser is not asked.
  const permissions = useQuery({
    ...myPermissionsQuery,
    retry: false,
    enabled: inOrganisation && !superuser,
  })
  const ruledOut =
    permissions.data?.known === true &&
    !permissions.data.codes.includes(TENANT_READ)
  const tenant = useQuery({
    ...currentTenantQuery,
    enabled:
      inOrganisation && (superuser || !permissions.isPending) && !ruledOut,
  })
  return tenant.data?.slug
}
