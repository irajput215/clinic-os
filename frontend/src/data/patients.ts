import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { PatientsService } from "@/client"
import type {
  AlertCreate,
  EmergencyContactCreate,
  PatientCreate,
  PatientStatusChange,
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

// MIRROR: patients/models.py PATIENT_STATUSES (manual §3.2): one status, coloured the same everywhere.
export const PATIENT_STATUSES = {
  CURRENT: { label: "Current", tone: "ok" },
  REVIEW: { label: "Review", tone: "info" },
  WAITING_LIST: { label: "Waiting list", tone: "purple" },
  CLAIMANT: { label: "Claimant", tone: "clay" },
  ARCHIVED: { label: "Archived", tone: "neutral" },
  DISCHARGED: { label: "Discharged", tone: "neutral" },
  BLOCKED: { label: "Blocked", tone: "danger" },
  DECEASED: { label: "Deceased", tone: "neutral" },
} as const
export type PatientStatus = keyof typeof PATIENT_STATUSES
/** The statuses a change must say why for (the server refuses without one). */
export const STATUSES_NEEDING_A_REASON: PatientStatus[] = [
  "BLOCKED",
  "ARCHIVED",
  "DISCHARGED",
]

const fetchPage = async (
  q: string,
  cursor: string | null,
  limit: number,
  status: PatientStatus[] = [],
): Promise<PatientsPublic> =>
  q
    ? (
        await PatientsService.searchPatients({
          body: { q, cursor, limit },
        })
      ).data
    : (
        await PatientsService.listPatients({
          query: { limit, cursor, status: status.length ? status : undefined },
        })
      ).data

/**
 * Every patient, or every match for `q`, a page at a time. The key sits under ["patients", "list"],
 * so a create or an edit (which invalidates that prefix) refreshes it.
 */
export const patientPagesQuery = (q: string, status: PatientStatus[] = []) =>
  infiniteQueryOptions({
    queryKey: ["patients", "list", "pages", q, status],
    queryFn: ({ pageParam }) =>
      fetchPage(q, pageParam, PATIENT_PAGE_LIMIT, status),
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

export const changePatientStatus = async (
  patientId: string,
  body: PatientStatusChange,
) =>
  (
    await PatientsService.changePatientStatus({
      path: { patient_id: patientId },
      body,
    })
  ).data

export const patientAlertsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId, "alerts"],
    queryFn: async () =>
      (
        await PatientsService.listPatientAlerts({
          path: { patient_id: patientId },
        })
      ).data,
    staleTime: 30_000,
  })

export const addPatientAlert = async (patientId: string, body: AlertCreate) =>
  (
    await PatientsService.addPatientAlert({
      path: { patient_id: patientId },
      body,
    })
  ).data

export const removePatientAlert = async (patientId: string, alertId: string) =>
  (
    await PatientsService.removePatientAlert({
      path: { patient_id: patientId, alert_id: alertId },
    })
  ).data

export const patientContactsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId, "contacts"],
    queryFn: async () =>
      (
        await PatientsService.listPatientEmergencyContacts({
          path: { patient_id: patientId },
        })
      ).data,
    staleTime: 30_000,
  })

export const addPatientContact = async (
  patientId: string,
  body: EmergencyContactCreate,
) =>
  (
    await PatientsService.addPatientEmergencyContact({
      path: { patient_id: patientId },
      body,
    })
  ).data

export const removePatientContact = async (
  patientId: string,
  contactId: string,
) =>
  (
    await PatientsService.removePatientEmergencyContact({
      path: { patient_id: patientId, contact_id: contactId },
    })
  ).data
