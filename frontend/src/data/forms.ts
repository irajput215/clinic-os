import { queryOptions } from "@tanstack/react-query"
import { FormsService } from "@/client"
import type {
  FormResponseCreate,
  FormResponseRead,
  InstrumentCatalogue,
  PatientForms,
  SafetyFlagRead,
} from "@/client/types.gen"

/**
 * Screening questionnaires (PHQ-9, GAD-7, K10), served by backend/app/modules/forms/router.py.
 * Recording needs `clinical_record:write`, reading `clinical_record:read`, both under the
 * care-relationship rule; the server scores, bands and raises safety flags. This layer only asks.
 */

export const instrumentsQuery = queryOptions({
  queryKey: ["forms", "instruments"],
  queryFn: async () =>
    (await FormsService.instruments()).data as InstrumentCatalogue,
  staleTime: Number.POSITIVE_INFINITY,
})

export const patientFormsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["forms", "patient", patientId],
    queryFn: async () =>
      (
        await FormsService.patientFormResponses({
          path: { patient_id: patientId },
        })
      ).data as PatientForms,
    staleTime: 15_000,
  })

export const formsRepo = {
  record: async (patientId: string, body: FormResponseCreate) =>
    (
      await FormsService.recordFormResponse({
        path: { patient_id: patientId },
        body,
      })
    ).data as FormResponseRead,
  acknowledge: async (flagId: string, actionCode: string) =>
    (
      await FormsService.acknowledgeSafetyFlag({
        path: { flag_id: flagId },
        body: { action_code: actionCode },
      })
    ).data as SafetyFlagRead,
}

/** Short names for the history and the buttons. */
export const INSTRUMENT_SHORT: Record<string, string> = {
  PHQ9: "PHQ-9",
  GAD7: "GAD-7",
  K10: "K10",
}

/** A band's tone: the published severity order, never a diagnosis. */
export const bandTone = (band: string): "ok" | "info" | "warn" | "danger" => {
  if (["MINIMAL", "LOW"].includes(band)) return "ok"
  if (["MILD", "MODERATE"].includes(band)) return "info"
  if (["MODERATELY_SEVERE", "HIGH"].includes(band)) return "warn"
  return "danger"
}
