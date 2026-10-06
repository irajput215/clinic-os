import { queryOptions } from "@tanstack/react-query"
import { apiCall } from "@/data/api"
import { sourceOf } from "@/data/capabilities"
import { previewMatch } from "@/data/preview/gate"
import { uuid } from "@/data/preview/seed"
import { readPreview, writePreview } from "@/data/preview/store"
import type {
  TgaApproval,
  TgaApprovalCreate,
  TgaMatchResponse,
} from "@/data/types"
import { clinicToday } from "@/lib/format"
import { Refusal } from "@/lib/http"

/**
 * TGA approvals. API routes (feat/tga-approvals-engine, backend/app/modules/tga_approvals/router.py):
 *   GET  /patients/{id}/tga-approvals     POST /tga-approvals
 *   GET  /tga-approvals/{id}              POST /tga-approvals/{id}/verify
 *   POST /tga-approvals/{id}/revoke       POST /tga-approvals/match
 * The tenant-wide register (`listAll`) has no route yet; it is proposed in
 * docs2/sdlc/05-approvals/api.md and served by the preview until then.
 */
interface ApprovalsRepo {
  listAll(): Promise<TgaApproval[]>
  listForPatient(patientId: string): Promise<TgaApproval[]>
  create(body: TgaApprovalCreate): Promise<TgaApproval>
  verify(id: string, applicationNumber: string): Promise<TgaApproval>
  revoke(id: string, reasonCode: string): Promise<TgaApproval>
  match(q: {
    patient_id: string
    tga_category: string
    dosage_form: string
    date_of_service: string
  }): Promise<TgaMatchResponse>
}

const api: ApprovalsRepo = {
  listAll: async () => {
    throw new Refusal(
      "NOT_AVAILABLE",
      "The approvals register needs GET /tga-approvals, which the API does not serve yet.",
    )
  },
  listForPatient: async (patientId) =>
    (
      await apiCall<{ data: TgaApproval[] }>(
        "GET",
        "/api/v1/patients/{patient_id}/tga-approvals",
        { path: { patient_id: patientId } },
      )
    ).data,
  create: (body) => apiCall("POST", "/api/v1/tga-approvals", { body }),
  verify: (id, applicationNumber) =>
    apiCall("POST", "/api/v1/tga-approvals/{approval_id}/verify", {
      path: { approval_id: id },
      body: { tga_application_number: applicationNumber },
    }),
  revoke: (id, reasonCode) =>
    apiCall("POST", "/api/v1/tga-approvals/{approval_id}/revoke", {
      path: { approval_id: id },
      body: { reason_code: reasonCode },
    }),
  match: (q) => apiCall("POST", "/api/v1/tga-approvals/match", { body: q }),
}

const MAX_YEARS = 2

const preview: ApprovalsRepo = {
  listAll: async () => (await readPreview()).approvals,
  listForPatient: async (patientId) =>
    (await readPreview()).approvals.filter((a) => a.patient_id === patientId),
  create: (body) =>
    writePreview((s) => {
      if (body.valid_to <= body.valid_from)
        throw new Refusal(
          "ERR_WINDOW_NOT_FORWARD",
          "The end date must be after the start date.",
        )
      const max = `${Number(body.valid_from.slice(0, 4)) + MAX_YEARS}${body.valid_from.slice(4)}`
      if (body.valid_to > max)
        throw new Refusal(
          "ERR_WINDOW_EXCEEDS_MAX_DURATION",
          "An approval can't be valid for more than two years.",
        )
      const now = new Date().toISOString()
      const row: TgaApproval = {
        id: uuid(),
        tenant_id: "",
        ...body,
        state: "PENDING",
        source: "MANUAL_ENTRY",
        created_by: s.me,
        verified_by: null,
        verified_at: null,
        revoked_by: null,
        revoked_at: null,
        revoked_reason_code: null,
        superseded_by_id: null,
        supersedes_id: null,
        created_at: now,
        updated_at: now,
      }
      s.approvals.unshift(row)
      return row
    }),
  verify: (id, applicationNumber) =>
    writePreview((s) => {
      const row = s.approvals.find((a) => a.id === id)
      if (!row)
        throw new Refusal(
          "TGA_APPROVAL_NOT_FOUND",
          "That approval isn't available.",
        )
      if (row.state !== "PENDING")
        throw new Refusal(
          "ILLEGAL_STATE_TRANSITION",
          "Only a pending approval can be verified.",
        )
      if (row.created_by === s.me)
        throw new Refusal(
          "VERIFIER_CANNOT_BE_CREATOR",
          "You entered this approval, so a second clinician must verify it.",
        )
      if (applicationNumber.trim() !== row.approval_reference)
        throw new Refusal(
          "TGA_APPLICATION_NUMBER_MISMATCH",
          "That reference doesn't match the approval. Re-enter it from the TGA letter.",
        )
      const overlaps = s.approvals.some(
        (a) =>
          a.id !== row.id &&
          a.state === "ACTIVE" &&
          a.patient_id === row.patient_id &&
          a.tga_category === row.tga_category &&
          a.dosage_form === row.dosage_form &&
          a.valid_from < row.valid_to &&
          row.valid_from < a.valid_to,
      )
      if (overlaps)
        throw new Refusal(
          "TGA_OVERLAPPING_ACTIVE_APPROVAL",
          "An active approval already covers these dates for this category and form. Supersede it instead.",
        )
      const now = new Date().toISOString()
      Object.assign(row, {
        state: row.valid_to <= clinicToday() ? "EXPIRED" : "ACTIVE",
        verified_by: s.me,
        verified_at: now,
        updated_at: now,
      })
      return row
    }),
  revoke: (id, reasonCode) =>
    writePreview((s) => {
      const row = s.approvals.find((a) => a.id === id)
      if (!row)
        throw new Refusal(
          "TGA_APPROVAL_NOT_FOUND",
          "That approval isn't available.",
        )
      if (row.state !== "PENDING" && row.state !== "ACTIVE")
        throw new Refusal(
          "ILLEGAL_STATE_TRANSITION",
          "This approval can no longer be revoked.",
        )
      const now = new Date().toISOString()
      Object.assign(row, {
        state: "REVOKED",
        revoked_by: s.me,
        revoked_at: now,
        revoked_reason_code: reasonCode,
        updated_at: now,
      })
      return row
    }),
  match: async (q) => previewMatch((await readPreview()).approvals, q),
}

export const approvalsRepo: ApprovalsRepo =
  sourceOf("tgaApprovals") === "api" ? api : preview

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
