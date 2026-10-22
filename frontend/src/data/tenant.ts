import { queryOptions } from "@tanstack/react-query"
import { TenantsService } from "@/client"
import { retryTransient } from "@/lib/http"

// No hooks in this module: the `_app` route's loader imports `clinicProfileQuery`, and anything here
// lands in the entry chunk, so a `useQuery` would pull React Query's observer into every first load.
// The hooks that read these queries are in `./useClinic`.

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

/** Renaming the clinic needs this code (Practice Owner). The server decides; this only hides. */
export const TENANT_CONFIGURE = "tenant:configure"

export const renameClinic = async (display_name: string) =>
  (
    await TenantsService.updateCurrentTenantProfile({
      body: { display_name },
    })
  ).data
