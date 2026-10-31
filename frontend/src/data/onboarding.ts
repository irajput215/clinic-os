import { queryOptions } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { AuthService, SopsService, UsersService } from "@/client"
import type {
  AcknowledgementMatrix,
  IdentifierUpdate,
  OnboardingPackRead,
  SopCard,
  SopDetail,
  SopWrite,
} from "@/client/types.gen"

/**
 * Staff onboarding (docs3 feature 02): a prescriber's pack and credential vault, and the practice's
 * SOPs. The server decides everything; these are the calls.
 *
 *   GET  /users/{id}/onboarding               the pack (self, tenant:configure or audit:read)
 *   PUT  /users/{id}/identifiers/{kind}       one identifier, with a step-up for that person
 *   POST /users/{id}/agreements               the signed agreement, attested by the caller
 *   GET  /sops · GET /sops/{id} · POST /sops · POST /sops/{id}/versions
 *   POST /sops/{id}/versions/{v}/acknowledge  · GET /sops/matrix
 */

export type IdentifierKind =
  | "AHPRA"
  | "HPI_I"
  | "PRESCRIBER_NUMBER"
  | "PROVIDER_NUMBER"

export const IDENTIFIER_HINTS: Record<IdentifierKind, string> = {
  AHPRA: "Three letters and 10 digits, e.g. MED0001234567",
  HPI_I: "16 digits starting 800361",
  PRESCRIBER_NUMBER: "7 digits",
  PROVIDER_NUMBER: "6 digits, a location character and a check letter",
}

export const ROLE_LABELS: Record<string, string> = {
  PRACTICE_OWNER: "Practice Owner",
  AUTHORISED_PRESCRIBER: "Authorised Prescriber",
  DOCTOR: "Doctor",
  NURSE: "Nurse",
  ADMINISTRATOR: "Administrator",
  PHARMACY: "Pharmacy",
  COMPLIANCE_AUDITOR: "Compliance / Auditor",
}

export const onboardingPackQuery = (userId: string) =>
  queryOptions({
    queryKey: ["onboarding", userId],
    queryFn: async (): Promise<OnboardingPackRead> =>
      (await UsersService.readOnboardingPack({ path: { user_id: userId } }))
        .data,
    staleTime: 60_000,
  })

export const updateIdentifier = async (
  userId: string,
  kind: IdentifierKind,
  body: Omit<IdentifierUpdate, "step_up_token">,
  password: string,
) => {
  const grant = await AuthService.stepUp({
    body: {
      password,
      operation: "practitioner.identifier_update",
      resource_id: userId,
    },
  })
  return (
    await UsersService.updateIdentifier({
      path: { user_id: userId, kind },
      body: { ...body, step_up_token: grant.data.step_up_token },
    })
  ).data
}

export const recordAgreement = async (
  userId: string,
  agreementVersion: string,
  signedOn: string,
) =>
  (
    await UsersService.recordAgreement({
      path: { user_id: userId },
      body: { agreement_version: agreementVersion, signed_on: signedOn },
    })
  ).data

/** How a missing pack item reads to a person (`missing` from the pack or the signing refusal). */
export function describeMissing(
  item: string,
  sopTitles: Record<string, string> = {},
): string {
  if (item === "AGREEMENT") return "Practitioner agreement not recorded"
  if (item === "AHPRA") return "AHPRA registration not verified"
  if (item === "PRESCRIBER_NUMBER") return "Prescriber number not verified"
  if (item.startsWith("SOP:")) {
    const title = sopTitles[item.slice(4)]
    return title
      ? `SOP not acknowledged: ${title}`
      : "A required SOP not acknowledged"
  }
  return item
}

export const sopsQuery = queryOptions({
  queryKey: ["sops"],
  queryFn: async (): Promise<SopCard[]> => (await SopsService.listSops()).data,
  staleTime: 60_000,
})

export const sopQuery = (sopId: string) =>
  queryOptions({
    queryKey: ["sops", sopId],
    queryFn: async (): Promise<SopDetail> =>
      (await SopsService.readSop({ path: { sop_id: sopId } })).data,
  })

export const matrixQuery = queryOptions({
  queryKey: ["sops", "matrix"],
  queryFn: async (): Promise<AcknowledgementMatrix> =>
    (await SopsService.acknowledgementMatrix()).data,
})

export const createSop = async (body: SopWrite) =>
  (await SopsService.createSop({ body })).data

export const publishSopVersion = async (sopId: string, body: SopWrite) =>
  (await SopsService.publishVersion({ path: { sop_id: sopId }, body })).data

export const acknowledgeSop = async (sopId: string, version: number) =>
  (await SopsService.acknowledge({ path: { sop_id: sopId, version } })).data

/** Whether `sop` waits for the caller's acknowledgement of its current version. */
export const needsAcknowledgement = (sop: SopCard) =>
  sop.applies_to_me && sop.my_acknowledged_version !== sop.current_version

/** The `missing` list of a `403 PRESCRIBER_NOT_READY` signing refusal, or `[]`. */
export function missingFromRefusal(error: unknown): string[] {
  if (!(error instanceof AxiosError)) return []
  const detail = (error.response?.data as { detail?: unknown } | undefined)
    ?.detail
  if (typeof detail !== "object" || detail === null) return []
  const missing = (detail as { missing?: unknown }).missing
  return Array.isArray(missing)
    ? missing.filter((m): m is string => typeof m === "string")
    : []
}
