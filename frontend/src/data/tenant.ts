import { queryOptions, useQuery } from "@tanstack/react-query"
import { TenantsService } from "@/client"
import { retryTransient } from "@/lib/http"
import { currentUserQuery } from "@/lib/session"
import { myPermissionsQuery } from "./permissions"

/**
 * The signed-in account's own organisation, `GET /api/v1/tenants/current`. The tenant comes from the
 * session on the server; nothing here names one.
 *
 * The routing `slug` builds the public booking link. The clinic's name comes from the profile read
 * below (`display_name`, PUBLIC); its `legal_name` is CONFIDENTIAL and no route returns it. This
 * route needs `tenant:read` (Practice Owner and Compliance / Auditor); anyone else is refused `403`,
 * and the app then offers no booking link.
 *
 * The slug only labels the sidebar, so a failure is never chased: the route is in the single-resource
 * read class (300/min per session), and a `429` is final like every other `4xx`, instead of
 * queuing retries that compete with the screen the person is actually using. A request that never
 * reached the API, or a `5xx`, gets the app's usual retries. The slug cannot change during a session;
 * a failed read is asked again on the next mount or window focus.
 */
export const TENANT_READ = "tenant:read"

export const currentTenantQuery = queryOptions({
  queryKey: ["session", "tenant"],
  queryFn: async () => (await TenantsService.readCurrentTenant()).data,
  staleTime: Number.POSITIVE_INFINITY,
  retry: retryTransient,
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

/**
 * The signed-in clinic's PUBLIC display name, `GET /api/v1/tenants/current/profile`. Every member of
 * the organisation may read it (no permission code: the public booking page shows it to anyone), so
 * the sidebar names the clinic for everybody. Never the CONFIDENTIAL `legal_name`, which no route
 * returns. Same retry and staleness rules as the tenant read above; a rename updates the cache.
 */
export const clinicProfileQuery = queryOptions({
  queryKey: ["session", "clinic-profile"],
  queryFn: async () => (await TenantsService.readCurrentTenantProfile()).data,
  staleTime: Number.POSITIVE_INFINITY,
  retry: retryTransient,
})

/** The clinic's display name, or `undefined` while unknown or for an account with no organisation. */
export function useClinicName(): string | undefined {
  const me = useQuery(currentUserQuery)
  const profile = useQuery({
    ...clinicProfileQuery,
    enabled: Boolean(me.data?.tenant_id),
  })
  return profile.data?.display_name
}

/** Renaming the clinic needs this code (Practice Owner). The server decides; this only hides. */
export const TENANT_CONFIGURE = "tenant:configure"

/**
 * Whether to offer the clinic settings: the account's known permissions include `tenant:configure`.
 * `undefined` while the answer loads (the tab is not offered yet, so it never appears and then
 * vanishes); when the set is unknown (a backend without `/users/me/permissions`) it is shown and the
 * server's `403` answers.
 */
export function useCanConfigureClinic(): boolean | undefined {
  const me = useQuery(currentUserQuery)
  const permissions = useQuery({
    ...myPermissionsQuery,
    retry: false,
    enabled: Boolean(me.data?.tenant_id) && !me.data?.is_superuser,
  })
  if (!me.data?.tenant_id || me.data.is_superuser) return false
  if (permissions.isPending) return undefined
  if (permissions.data?.known)
    return permissions.data.codes.includes(TENANT_CONFIGURE)
  return true
}

export const renameClinic = async (display_name: string) =>
  (
    await TenantsService.updateCurrentTenantProfile({
      body: { display_name },
    })
  ).data
