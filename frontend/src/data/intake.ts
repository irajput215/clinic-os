import { queryOptions } from "@tanstack/react-query"
import { IntakeService, PublicBookingService } from "@/client"
import type {
  ApplicationCard,
  ApplicationDetail,
  ConsentRecord,
  IntakeBriefing,
  IntakeForm,
  PharmacyCreate,
  PharmacyRead,
  RejectBody,
} from "@/client/types.gen"

/**
 * Patient intake (docs3 feature 03), served by backend/app/modules/intake:
 *   GET  /public/{slug}/intake-form            consents (current versions) and partner pharmacies
 *   POST /public/{slug}/bookings + application  the six-step application, held with its booking
 *   GET  /intake-applications?status=          the clinic's queue · GET /{id} · POST /{id}/accept|reject
 *   GET  /patients/{id}/intake-briefing        the doctor's briefing · GET /patients/{id}/consents
 *   GET|POST /pharmacies                       the directory · POST /patients/{id}/pharmacy
 */

// MIRROR: intake/schemas.py PrimaryCondition, CannabisForm, CannabisDuration.
export const CONDITIONS = {
  CHRONIC_PAIN: "Chronic pain",
  SLEEP: "Sleep",
  ANXIETY: "Anxiety",
  DEPRESSION: "Depression",
  PTSD: "PTSD",
  NAUSEA: "Nausea or vomiting",
  NEUROLOGICAL: "Neurological condition",
  OTHER: "Something else",
} as const
export const CANNABIS_FORMS = {
  DRY_HERB: "Dried flower",
  OIL: "Oil",
  CAPSULE: "Capsule",
  VAPE: "Vape cartridge",
  EDIBLE: "Edible",
  OTHER: "Other",
} as const
export const CANNABIS_DURATIONS = {
  LESS_THAN_6_MONTHS: "Less than 6 months",
  SIX_TO_24_MONTHS: "6 months to 2 years",
  MORE_THAN_2_YEARS: "More than 2 years",
} as const
export const FLAG_LABELS: Record<string, string> = {
  PSYCHOSIS_HISTORY: "Psychosis history",
  PREGNANT_OR_BREASTFEEDING: "Pregnant or breastfeeding",
  HEART_CONDITION: "Heart condition",
  SUBSTANCE_DEPENDENCE: "Substance dependence",
  NO_CONVENTIONAL_THERAPY: "No standard treatment tried",
  CANNABIS_NAIVE: "Never used before",
}
export const REJECT_REASONS = {
  NOT_ELIGIBLE: "Not eligible",
  NEEDS_IN_PERSON_REVIEW: "Needs an in-person review",
  DUPLICATE: "Duplicate application",
  INCOMPLETE: "Incomplete",
  OTHER: "Other",
} as const

export const intakeFormQuery = (clinicSlug: string) =>
  queryOptions({
    queryKey: ["public-intake-form", clinicSlug],
    queryFn: async (): Promise<IntakeForm> =>
      (
        await PublicBookingService.bookingReadIntakeForm({
          path: { clinic_slug: clinicSlug },
        })
      ).data,
    staleTime: 5 * 60_000,
  })

export type ApplicationStatus = "SUBMITTED" | "ACCEPTED" | "REJECTED"

export const applicationsQuery = (status: ApplicationStatus = "SUBMITTED") =>
  queryOptions({
    queryKey: ["intake", "applications", status],
    queryFn: async (): Promise<ApplicationCard[]> =>
      (await IntakeService.listApplications({ query: { status } })).data,
    staleTime: 15_000,
  })

export const applicationQuery = (applicationId: string) =>
  queryOptions({
    queryKey: ["intake", "application", applicationId],
    queryFn: async (): Promise<ApplicationDetail> =>
      (
        await IntakeService.readApplication({
          path: { application_id: applicationId },
        })
      ).data,
  })

export const acceptApplication = async (applicationId: string) =>
  (
    await IntakeService.acceptApplication({
      path: { application_id: applicationId },
    })
  ).data

export const rejectApplication = async (
  applicationId: string,
  body: RejectBody,
) =>
  (
    await IntakeService.rejectApplication({
      path: { application_id: applicationId },
      body,
    })
  ).data

export const briefingQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId, "briefing"],
    // The generated client turns a `null` body into `{}`, so "never applied" is told apart by shape.
    queryFn: async (): Promise<IntakeBriefing | null> => {
      const { data } = await IntakeService.readIntakeBriefing({
        path: { patient_id: patientId },
      })
      return data && "safety_flags" in data ? data : null
    },
    staleTime: 60_000,
  })

export const consentsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["patients", "detail", patientId, "consents"],
    queryFn: async (): Promise<ConsentRecord[]> =>
      (
        await IntakeService.listPatientConsents({
          path: { patient_id: patientId },
        })
      ).data,
    staleTime: 60_000,
  })

export const pharmaciesQuery = queryOptions({
  queryKey: ["pharmacies"],
  queryFn: async (): Promise<PharmacyRead[]> =>
    (await IntakeService.listPharmacies()).data,
  staleTime: 60_000,
})

export const createPharmacy = async (body: PharmacyCreate) =>
  (await IntakeService.createPharmacy({ body })).data

export const setPatientPharmacy = async (
  patientId: string,
  pharmacyId: string | null,
) =>
  (
    await IntakeService.setPatientPharmacy({
      path: { patient_id: patientId },
      body: { pharmacy_id: pharmacyId },
    })
  ).data
