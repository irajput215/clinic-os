import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query"
import { TgaApprovalsService } from "@/client"
import type {
  TgaApprovalRegister,
  TgaApprovalRegisterCounts,
} from "@/client/types.gen"
import {
  APPROVAL_STATES,
  type ApprovalState,
  type TgaApproval,
  type TgaApprovalCreate,
} from "@/data/types"

/**
 * TGA approvals, served by backend/app/modules/tga_approvals/router.py:
 *   GET  /tga-approvals (the practice-wide register)    GET /patients/{id}/tga-approvals
 *   POST /tga-approvals    POST /tga-approvals/{id}/verify    POST /tga-approvals/{id}/revoke
 * Refusals come back as RFC 7807 with `detail.code` (VERIFIER_CANNOT_BE_CREATOR,
 * TGA_APPLICATION_NUMBER_MISMATCH, TGA_OVERLAPPING_ACTIVE_APPROVAL, ILLEGAL_STATE_TRANSITION) and
 * are worded in lib/http.ts.
 *
 * The generated SDK types `state` and `source` as plain strings; `TgaApproval` (data/types.ts)
 * narrows them to the values the backend's schema allows, so the reads are typed with it.
 */

/** The API's largest page (tga_approvals/service.py `MAX_PAGE_SIZE`). */
const PAGE_SIZE = 100

/** A register row: an approval plus its patient's display name (`null` once the record is gone). */
export type RegisterRow = TgaApproval & { patient_display_name: string | null }
export type RegisterPage = Omit<TgaApprovalRegister, "data"> & {
  data: RegisterRow[]
}
export type RegisterCounts = TgaApprovalRegisterCounts

/** The register's "Needs action" window (docs2/sdlc/05-approvals/requirements.md). */
export const EXPIRING_WINDOW_DAYS = 30

const INACTIVE_STATES: ApprovalState[] = APPROVAL_STATES.filter(
  (s) => s !== "ACTIVE" && s !== "PENDING",
)

type RegisterQuery = {
  state?: ApprovalState[]
  expiring_within_days?: number
}

/**
 * The register's filters (R7). Each is a query the server answers, so paging and counts are the
 * server's, never a filter over whatever happened to be loaded. `state` and `expiring_within_days`
 * are a union server-side, which is what makes "Needs action" a single keyset.
 */
export const REGISTER_FILTERS: Record<
  "attention" | "active" | "pending" | "inactive" | "all",
  {
    label: string
    query: RegisterQuery
    count: (c: RegisterCounts) => number
  }
> = {
  attention: {
    label: "Needs action",
    query: { state: ["PENDING"], expiring_within_days: EXPIRING_WINDOW_DAYS },
    count: (c) => (c.by_state.PENDING ?? 0) + c.expiring,
  },
  active: {
    label: "Active",
    query: { state: ["ACTIVE"] },
    count: (c) => c.by_state.ACTIVE ?? 0,
  },
  pending: {
    label: "Pending",
    query: { state: ["PENDING"] },
    count: (c) => c.by_state.PENDING ?? 0,
  },
  inactive: {
    label: "Expired & revoked",
    query: { state: INACTIVE_STATES },
    count: (c) => INACTIVE_STATES.reduce((n, s) => n + (c.by_state[s] ?? 0), 0),
  },
  all: {
    label: "All",
    query: {},
    count: (c) => Object.values(c.by_state).reduce((n, v) => n + v, 0),
  },
}
export type RegisterFilter = keyof typeof REGISTER_FILTERS
export const REGISTER_FILTER_KEYS = Object.keys(
  REGISTER_FILTERS,
) as RegisterFilter[]

/** The register's page size: enough to scan, small enough to keep each audited read bounded. */
export const REGISTER_PAGE_SIZE = 50

const readRegister = async (
  query: RegisterQuery,
  limit: number,
  cursor?: string,
) =>
  (
    await TgaApprovalsService.approvalsListTgaApprovals({
      query: { ...query, limit, cursor },
    })
  ).data as RegisterPage

export const approvalsRepo = {
  /** One page of the practice-wide register for a filter, plus the practice's totals. */
  register: (filter: RegisterFilter, cursor?: string) =>
    readRegister(REGISTER_FILTERS[filter].query, REGISTER_PAGE_SIZE, cursor),
  /** Every approval on file for the patient: all keyset pages, so none is silently dropped. */
  listForPatient: async (patientId: string) => {
    const approvals: TgaApproval[] = []
    let cursor: string | undefined
    do {
      const { data: page } =
        await TgaApprovalsService.approvalsListPatientTgaApprovals({
          path: { patient_id: patientId },
          query: { limit: PAGE_SIZE, cursor },
        })
      approvals.push(...(page.data as TgaApproval[]))
      cursor = page.next_cursor ?? undefined
    } while (cursor)
    return approvals
  },
  create: async (body: TgaApprovalCreate) =>
    (await TgaApprovalsService.approvalsCreateTgaApproval({ body }))
      .data as TgaApproval,
  verify: async (id: string, applicationNumber: string) =>
    (
      await TgaApprovalsService.approvalsVerifyTgaApproval({
        path: { approval_id: id },
        body: { tga_application_number: applicationNumber.trim() },
      })
    ).data as TgaApproval,
  revoke: async (id: string, reasonCode: string) =>
    (
      await TgaApprovalsService.approvalsRevokeTgaApproval({
        path: { approval_id: id },
        body: { reason_code: reasonCode },
      })
    ).data as TgaApproval,
}

/** The register for one filter, a keyset page at a time ("Show more" fetches the next). */
export const registerQuery = (filter: RegisterFilter) =>
  infiniteQueryOptions({
    queryKey: ["approvals", "register", filter],
    queryFn: ({ pageParam }) => approvalsRepo.register(filter, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    staleTime: 15_000,
  })

/** The practice's totals alone (one row asked for), for the sidebar's pending count. */
export const approvalCountsQuery = queryOptions({
  queryKey: ["approvals", "counts"],
  queryFn: async () => (await readRegister({}, 1)).counts,
  staleTime: 30_000,
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
