import { queryOptions } from "@tanstack/react-query"
import { AuditService } from "@/client"

/**
 * The append-only, hash-chained audit trail (backend/app/modules/audit).
 * `GET /api/v1/audit/events` needs `audit:read`; a caller without it gets `403`, which the screen
 * shows as "not available to your role" rather than an error.
 */
export const resourceAuditQuery = (resourceId: string) =>
  queryOptions({
    queryKey: ["audit", "resource", resourceId],
    queryFn: async () =>
      (
        await AuditService.listAuditEvents({
          query: { resource_id: resourceId, limit: 50 },
        })
      ).data.data,
    staleTime: 30_000,
  })

/** `patient.read` → `Patient read`. */
export const actionLabel = (action: string) => {
  const text = action.replace(/[._]/g, " ")
  return text[0].toUpperCase() + text.slice(1)
}
