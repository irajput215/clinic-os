import { queryOptions } from "@tanstack/react-query"
import { FormsService } from "@/client"
import type {
  ClinicFormRead,
  ClinicFormResponseRead,
  ClinicFormWrite,
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

/** Clinic-made forms (R6): active ones for staff; with retired ones for `tenant:configure`. */
export const clinicFormsQuery = (includeRetired = false) =>
  queryOptions({
    queryKey: ["forms", "clinic", includeRetired],
    queryFn: async () =>
      (
        await FormsService.clinicForms({
          query: { include_retired: includeRetired },
        })
      ).data as ClinicFormRead[],
    staleTime: 30_000,
  })

export type AnswerValue = string | number | boolean | null

export const clinicFormsRepo = {
  create: async (body: ClinicFormWrite) =>
    (await FormsService.createClinicForm({ body })).data as ClinicFormRead,
  publishVersion: async (formId: string, body: ClinicFormWrite) =>
    (
      await FormsService.publishClinicFormVersion({
        path: { form_id: formId },
        body,
      })
    ).data as ClinicFormRead,
  retire: async (formId: string) =>
    (await FormsService.retireClinicForm({ path: { form_id: formId } }))
      .data as ClinicFormRead,
  respond: async (
    patientId: string,
    formVersionId: string,
    answers: Record<string, AnswerValue>,
  ) =>
    (
      await FormsService.recordClinicFormResponse({
        path: { patient_id: patientId },
        body: { form_version_id: formVersionId, answers },
      })
    ).data as ClinicFormResponseRead,
}

export const FIELD_TYPE_LABELS: Record<string, string> = {
  TEXT: "Short text",
  LONG_TEXT: "Long text",
  CHOICE: "Choice",
  SCALE: "Scale (0 to 10)",
  DATE: "Date",
  YES_NO: "Yes / no",
}

/** A field's answer, for reading back in the history. */
export const formatAnswer = (value: AnswerValue | undefined): string => {
  if (value === undefined || value === null || value === "") return "—"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  return String(value)
}
