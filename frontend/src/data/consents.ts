import { queryOptions } from "@tanstack/react-query"
import { ConsentsService } from "@/client"
import type {
  ConsentDocumentRead,
  ConsentLibrary,
  PatientConsentStatus,
} from "@/client/types.gen"

/**
 * The consent library (docs3 Phase 6 feature 06), served by backend/app/modules/consents/router.py.
 * Publishing needs `tenant:configure`; a patient's consents need `patient:read` to see and
 * `patient:update` to record or withdraw, under the care-relationship rule. The server decides what
 * is current; a consent on an older text reads "needs re-consent" until the patient agrees again.
 */

export type ConsentKind = "PRIVACY" | "TELEHEALTH" | "TREATMENT"

export const consentLibraryQuery = queryOptions({
  queryKey: ["consents", "library"],
  queryFn: async () =>
    (await ConsentsService.consentLibrary()).data as ConsentLibrary,
  staleTime: 30_000,
})

export const patientConsentsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId, "consents"],
    queryFn: async () =>
      (
        await ConsentsService.patientConsents({
          path: { patient_id: patientId },
        })
      ).data as PatientConsentStatus,
    staleTime: 30_000,
  })

export const consentsRepo = {
  publish: async (kind: ConsentKind, title: string, body: string) =>
    (
      await ConsentsService.publishConsent({
        path: { kind },
        body: { title, body },
      })
    ).data as ConsentDocumentRead,
  record: async (patientId: string, kind: ConsentKind, version: string) =>
    (
      await ConsentsService.recordConsent({
        path: { patient_id: patientId },
        body: { kind, version },
      })
    ).data as PatientConsentStatus,
  withdraw: async (
    patientId: string,
    kind: ConsentKind,
    method: "IN_PERSON" | "PHONE" | "WRITTEN",
  ) =>
    (
      await ConsentsService.withdrawConsent({
        path: { patient_id: patientId, kind },
        body: { method },
      })
    ).data as PatientConsentStatus,
}

export const STATUS_LABEL: Record<
  string,
  { label: string; tone: "ok" | "warn" | "danger" | "neutral" }
> = {
  CURRENT: { label: "Current", tone: "ok" },
  NEEDS_RECONSENT: { label: "Re-consent needed", tone: "warn" },
  WITHDRAWN: { label: "Withdrawn", tone: "danger" },
  NOT_GIVEN: { label: "Not given", tone: "neutral" },
}
