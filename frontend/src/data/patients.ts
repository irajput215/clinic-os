import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { PatientsService } from "@/client"
import type {
  PatientCreate,
  PatientsPublic,
  PatientUpdate,
} from "@/client/types.gen"

/**
 * Patients are served by the backend (backend/app/modules/patients).
 *
 * - `GET /patients?limit=&cursor=` pages through every patient, keyset-ordered by family name.
 * - `POST /patients/search` finds patients by name prefix, date of birth or PT- reference. The term
 *   travels in the request body and is never put in a URL (the app's own or the API's), so it stays
 *   out of browser history and access logs.
 */
export const PATIENT_PAGE_LIMIT = 25

/** The first page only. Kept for the pickers and name lookups of other features. */
export const patientsQuery = queryOptions({
  queryKey: ["patients", "list"],
  queryFn: async () =>
    (
      await PatientsService.listPatients({
        query: { limit: PATIENT_PAGE_LIMIT },
      })
    ).data,
  staleTime: 30_000,
})

const fetchPage = async (
  q: string,
  cursor: string | null,
  limit: number,
): Promise<PatientsPublic> =>
  q
    ? (
        await PatientsService.searchPatients({
          body: { q, cursor, limit },
        })
      ).data
    : (
        await PatientsService.listPatients({
          query: { limit, cursor },
        })
      ).data

/**
 * Every patient, or every match for `q`, a page at a time. The key sits under ["patients", "list"],
 * so a create or an edit (which invalidates that prefix) refreshes it.
 */
export const patientPagesQuery = (q: string) =>
  infiniteQueryOptions({
    queryKey: ["patients", "list", "pages", q],
    queryFn: ({ pageParam }) => fetchPage(q, pageParam, PATIENT_PAGE_LIMIT),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    staleTime: 30_000,
  })

/** The top-bar quick-find: the first few matches only. */
export const QUICK_FIND_LIMIT = 6

export const patientQuickFindQuery = (q: string) =>
  queryOptions({
    queryKey: ["patients", "list", "quick-find", q],
    queryFn: () => fetchPage(q, null, QUICK_FIND_LIMIT),
    staleTime: 30_000,
  })

/** The search term the server is asked about: trimmed, and only once typing has paused. */
export function useSearchTerm(value: string, delayMs = 250) {
  const [settled, setSettled] = useState(value.trim())
  useEffect(() => {
    const next = value.trim()
    if (!next) {
      setSettled("")
      return
    }
    const timer = setTimeout(() => setSettled(next), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

export const patientQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId],
    queryFn: async () =>
      (await PatientsService.readPatient({ path: { patient_id: patientId } }))
        .data,
    staleTime: 30_000,
  })

export const createPatient = async (body: PatientCreate) =>
  (await PatientsService.createPatient({ body })).data

export const updatePatient = async (patientId: string, body: PatientUpdate) =>
  (
    await PatientsService.updatePatient({
      path: { patient_id: patientId },
      body,
    })
  ).data

export const patientName = (p: {
  given_name: string
  family_name: string
  preferred_name?: string | null
}) => `${p.preferred_name || p.given_name} ${p.family_name}`
