import { queryOptions } from "@tanstack/react-query"
import { PatientsService } from "@/client"
import type { PatientCreate, PatientUpdate } from "@/client/types.gen"

/**
 * Patients are served by the backend (backend/app/modules/patients). The list is bounded at 25 by
 * the API (no search or paging yet), so the UI filters the loaded page locally and says so.
 */
export const PATIENT_PAGE_LIMIT = 25

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
