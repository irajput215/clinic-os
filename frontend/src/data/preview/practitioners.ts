import { queryOptions } from "@tanstack/react-query"
import type { Practitioner } from "@/data/types"
import { readPreview } from "./store"

/**
 * The preview store's sample practitioners. PREVIEW ONLY, for the two features still on preview
 * whose sample records name them: the Today page (`dashboard`, its sample appointments) and the
 * script queue (`prescriptions`, the prescriber of a staged script). The calendar reads the real
 * roster (`practitionersQuery` in data/appointments.ts). This goes when those two modules land.
 */
export const previewPractitionersQuery = queryOptions({
  queryKey: ["preview", "practitioners"],
  queryFn: async (): Promise<Practitioner[]> =>
    (await readPreview()).practitioners,
  staleTime: 5 * 60_000,
})
