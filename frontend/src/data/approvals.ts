import { queryOptions } from "@tanstack/react-query"
import { apiCall } from "@/data/api"
import type { TgaApproval, TgaApprovalCreate } from "@/data/types"
import { Refusal } from "@/lib/http"

/**
 * TGA approvals, served by backend/app/modules/tga_approvals/router.py:
 *   GET  /patients/{id}/tga-approvals     POST /tga-approvals
 *   POST /tga-approvals/{id}/verify       POST /tga-approvals/{id}/revoke
 * Refusals come back as RFC 7807 with `detail.code` (VERIFIER_CANNOT_BE_CREATOR,
 * TGA_APPLICATION_NUMBER_MISMATCH, TGA_OVERLAPPING_ACTIVE_APPROVAL, ILLEGAL_STATE_TRANSITION) and
 * are worded in lib/http.ts.
 *
 * The practice-wide register has no route: `GET /tga-approvals` is proposed in
 * docs2/sdlc/05-approvals/api.md. Until it lands, `listAll` is a designed refusal rather than a
 * guess, and the register screen says so.
 */

/** The API's largest page (tga_approvals/service.py `MAX_PAGE_SIZE`). */
const PAGE_SIZE = 100

/** The refusal code `listAll` raises while `GET /tga-approvals` does not exist. */
export const REGISTER_NOT_AVAILABLE = "NOT_AVAILABLE"

interface ApprovalsPage {
  data: TgaApproval[]
  count: number
  next_cursor: string | null
}

export const approvalsRepo = {
  listAll: async (): Promise<TgaApproval[]> => {
    throw new Refusal(
      REGISTER_NOT_AVAILABLE,
      "The practice-wide register needs GET /api/v1/tga-approvals, which the API doesn't serve yet.",
    )
  },
  /** Every approval on file for the patient: all keyset pages, so none is silently dropped. */
  listForPatient: async (patientId: string) => {
    const approvals: TgaApproval[] = []
    let cursor: string | undefined
    do {
      const page = await apiCall<ApprovalsPage>(
        "GET",
        "/api/v1/patients/{patient_id}/tga-approvals",
        {
          path: { patient_id: patientId },
          query: { limit: PAGE_SIZE, cursor },
        },
      )
      approvals.push(...page.data)
      cursor = page.next_cursor ?? undefined
    } while (cursor)
    return approvals
  },
  create: (body: TgaApprovalCreate) =>
    apiCall<TgaApproval>("POST", "/api/v1/tga-approvals", { body }),
  verify: (id: string, applicationNumber: string) =>
    apiCall<TgaApproval>("POST", "/api/v1/tga-approvals/{approval_id}/verify", {
      path: { approval_id: id },
      body: { tga_application_number: applicationNumber.trim() },
    }),
  revoke: (id: string, reasonCode: string) =>
    apiCall<TgaApproval>("POST", "/api/v1/tga-approvals/{approval_id}/revoke", {
      path: { approval_id: id },
      body: { reason_code: reasonCode },
    }),
}

export const approvalsQuery = queryOptions({
  queryKey: ["approvals", "all"],
  queryFn: () => approvalsRepo.listAll(),
  staleTime: 15_000,
})

export const patientApprovalsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["approvals", "patient", patientId],
    queryFn: () => approvalsRepo.listForPatient(patientId),
    staleTime: 15_000,
  })

/** TGA categories and dosage forms, as the backend's `^[A-Z0-9_]+$` codes with display labels. */
export const TGA_CATEGORIES: Record<string, string> = {
  CATEGORY_1: "Category 1 · CBD ≥ 98%",
  CATEGORY_2: "Category 2 · CBD-dominant",
  CATEGORY_3: "Category 3 · Balanced",
  CATEGORY_4: "Category 4 · THC-dominant",
  CATEGORY_5: "Category 5 · THC ≥ 98%",
}

export const DOSAGE_FORMS: Record<string, string> = {
  ORAL_LIQUID: "Oral liquid",
  DRIED_FLOWER: "Dried flower",
  CAPSULE: "Capsule",
  OROMUCOSAL_SPRAY: "Oromucosal spray",
  TOPICAL: "Topical",
}

export const REVOKE_REASONS: Record<string, string> = {
  CLINICAL_DECISION: "Clinical decision",
  PATIENT_REQUEST: "Patient request",
  ENTERED_IN_ERROR: "Entered in error",
  TGA_WITHDRAWN: "Withdrawn by the TGA",
}

export const CREATION_REASONS: Record<string, string> = {
  NEW_APPLICATION: "New SAS-B / AP approval",
  RENEWAL: "Renewal",
  TRANSFERRED_IN: "Transferred from another prescriber",
}

export const categoryShort = (code: string) => code.replace("CATEGORY_", "Cat ")
export const formLabel = (code: string) => DOSAGE_FORMS[code] ?? code
