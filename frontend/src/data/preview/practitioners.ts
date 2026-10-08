import { queryOptions } from "@tanstack/react-query"
import type { Practitioner } from "@/data/types"
import { readPreview } from "./store"

/**
 * The preview store's sample practitioners. PREVIEW ONLY, for the Today page (`dashboard`, its
 * sample appointments). The calendar reads the real roster (`practitionersQuery` in
 * data/appointments.ts) and the script queue reads `GET /prescriptions/prescribers`. This goes when
 * the dashboard module lands.
 */
export const previewPractitionersQuery = queryOptions({
  queryKey: ["preview", "practitioners"],
  queryFn: async (): Promise<Practitioner[]> =>
    (await readPreview()).practitioners,
  staleTime: 5 * 60_000,
})
