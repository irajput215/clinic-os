import { queryOptions } from "@tanstack/react-query"
import { DashboardService } from "@/client"
import type {
  PrescriptionQueueSummary,
  TgaApprovalDigest,
  TodaySummary,
} from "@/client/types.gen"
import type { RegisterRow } from "@/data/approvals"
import type { Prescription } from "@/data/scripts"

/**
 * The Today page in one round trip: `GET /api/v1/dashboard/today`
 * (backend/app/modules/dashboard, docs2/sdlc/08-today/api.md, Milestone 2 phase 2E).
 *
 * The server reads every section in one tenant transaction, through the modules that own the data,
 * and evaluates each actionable script's safety gate now. A section the caller's role cannot read is
 * `null` and named in `withheld`: it was never read, so the page shows the role boundary instead.
 */
export type Today = Omit<TodaySummary, "scripts" | "approvals"> & {
  scripts:
    | (Omit<PrescriptionQueueSummary, "actionable"> & {
        actionable: Prescription[]
      })
    | null
  approvals:
    | (Omit<TgaApprovalDigest, "pending" | "expiring_soon"> & {
        pending: RegisterRow[]
        expiring_soon: RegisterRow[]
      })
    | null
}

export const todayQuery = queryOptions({
  queryKey: ["dashboard", "today"],
  // The generated types are wider than the backend's vocabularies (state, reason codes); `Today`
  // narrows them the same way `scripts.ts` and `approvals.ts` narrow their own reads.
  queryFn: async () => (await DashboardService.readToday()).data as Today,
  staleTime: 15_000,
})
