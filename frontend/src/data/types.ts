/**
 * Domain types for the features whose backend modules are not in the generated client yet.
 *
 * Two kinds live here, and the comment on each says which:
 * - MIRROR: copied field-for-field from a backend module that exists on a branch
 *   (backend/app/modules/<module>/schemas.py). When that module merges, the generated client's type
 *   replaces the mirror and the compiler points at every difference.
 * - PROPOSED: no backend module exists. The shape is this app's proposed contract, written up in
 *   docs2/sdlc/<feature>/api.md for the backend owner to accept or amend.
 */

// MIRROR: tga_approvals/models.py APPROVAL_STATES
export const APPROVAL_STATES = [
  "PENDING",
  "ACTIVE",
  "EXPIRED",
  "REJECTED",
  "REVOKED",
  "SUPERSEDED",
] as const
export type ApprovalState = (typeof APPROVAL_STATES)[number]

// MIRROR: tga_approvals/schemas.py TgaApprovalRead
export interface TgaApproval {
  id: string
  tenant_id: string
  patient_id: string
  tga_category: string
  dosage_form: string
  approval_reference: string
  /** Inclusive first day. */
  valid_from: string
  /** EXCLUSIVE: the window is half-open `[valid_from, valid_to)` (D-006). */
  valid_to: string
  state: ApprovalState
  source: "MANUAL_ENTRY" | "INBOX_EXTRACTION"
  created_by: string
  verified_by: string | null
  verified_at: string | null
  revoked_by: string | null
  revoked_at: string | null
  revoked_reason_code: string | null
  superseded_by_id: string | null
  supersedes_id: string | null
  created_at: string
  updated_at: string
}

// MIRROR: tga_approvals/schemas.py TgaApprovalCreate
export interface TgaApprovalCreate {
  patient_id: string
  tga_category: string
  dosage_form: string
  approval_reference: string
  creation_reason: string
  valid_from: string
  valid_to: string
}

// MIRROR: tga_approvals/service.py MatchReason
export const MATCH_REASONS = {
  TGA_APPROVAL_NOT_FOUND: "No TGA approval on file for this patient",
  TGA_CATEGORY_MISMATCH: "Approval is for a different TGA category",
  TGA_DOSAGE_FORM_MISMATCH: "Approval is for a different dosage form",
  TGA_APPROVAL_EXPIRED: "Approval had expired on the date of service",
  TGA_APPROVAL_NOT_YET_EFFECTIVE:
    "Approval had not started on the date of service",
  TGA_APPROVAL_REVOKED: "Approval was revoked",
  TGA_APPROVAL_PENDING_VERIFICATION:
    "Approval is waiting for a second clinician to verify it",
  TGA_APPROVAL_SUPERSEDED: "Approval was replaced by a newer grant",
  TGA_APPROVAL_REJECTED: "Approval was rejected at verification",
} as const
export type MatchReason = keyof typeof MATCH_REASONS

/** Two-to-three word forms of the same reasons, for pills in dense lists. */
export const MATCH_REASONS_SHORT: Record<MatchReason, string> = {
  TGA_APPROVAL_NOT_FOUND: "No approval",
  TGA_CATEGORY_MISMATCH: "Wrong category",
  TGA_DOSAGE_FORM_MISMATCH: "Wrong dosage form",
  TGA_APPROVAL_EXPIRED: "Approval expired",
  TGA_APPROVAL_NOT_YET_EFFECTIVE: "Not yet valid",
  TGA_APPROVAL_REVOKED: "Approval revoked",
  TGA_APPROVAL_PENDING_VERIFICATION: "Awaiting verification",
  TGA_APPROVAL_SUPERSEDED: "Approval superseded",
  TGA_APPROVAL_REJECTED: "Approval rejected",
}

// MIRROR: tga_approvals/schemas.py TgaMatchResponse
export interface TgaMatchResponse {
  matched: boolean
  reason_code: MatchReason | null
  state: ApprovalState | null
  approval_id: string | null
  validity_interval: {
    valid_from: string
    valid_to: string
    bounds: "[)"
  } | null
  date_of_service: string
  evaluated_timezone: string
}

// MIRROR: clinical_records/schemas.py ClinicalRecordVersionRead
export interface ClinicalRecordVersion {
  id: string
  clinical_record_id: string
  version: number
  body: string
  body_format: string
  author_id: string
  signed_at: string | null
  supersedes_version: number | null
  amendment_reason: string | null
  created_at: string
}

// MIRROR: clinical_records/schemas.py ClinicalRecordSummary
export interface ClinicalRecordSummary {
  id: string
  patient_id: string
  record_type: string
  author_id: string
  current_version: number
  signed_at: string | null
  deleted_at: string | null
  created_at: string
  latest_version: ClinicalRecordVersion
}

// MIRROR: clinical_records/schemas.py SoapNote
export interface SoapNote {
  subjective?: string | null
  objective?: string | null
  assessment?: string | null
  plan?: string | null
}

// PROPOSED: a person who can be booked. Resolved from users + roles server-side.
export interface Practitioner {
  id: string
  name: string
  role: "DOCTOR" | "NURSE"
  title: string
}

// PROPOSED: appointments module (docs2/sdlc/04-calendar-and-booking/api.md)
export const APPOINTMENT_TYPES = {
  NURSE_TRIAGE: { label: "Free nurse triage", minutes: 15, role: "NURSE" },
  INITIAL_CONSULT: {
    label: "Initial consult (doctor)",
    minutes: 30,
    role: "DOCTOR",
  },
  FOLLOW_UP: { label: "Follow-up consult", minutes: 15, role: "DOCTOR" },
} as const
export type AppointmentType = keyof typeof APPOINTMENT_TYPES

export const APPOINTMENT_STATUSES = [
  "BOOKED",
  "CONFIRMED",
  "ARRIVED",
  "COMPLETED",
  "CANCELLED",
  "NO_SHOW",
] as const
export type AppointmentStatus = (typeof APPOINTMENT_STATUSES)[number]

export const APPOINTMENT_TRANSITIONS: Record<
  AppointmentStatus,
  AppointmentStatus[]
> = {
  BOOKED: ["CONFIRMED", "ARRIVED", "CANCELLED", "NO_SHOW"],
  CONFIRMED: ["ARRIVED", "CANCELLED", "NO_SHOW"],
  ARRIVED: ["COMPLETED"],
  COMPLETED: [],
  CANCELLED: [],
  NO_SHOW: [],
}

export interface Appointment {
  id: string
  patient_id: string
  patient_name: string
  practitioner_id: string
  type: AppointmentType
  status: AppointmentStatus
  /** Half-open `[starts_at, ends_at)`, ISO instants. */
  starts_at: string
  ends_at: string
  source: "STAFF" | "PUBLIC_BOOKING"
  created_at: string
}

// PROPOSED: products module (drug catalogue). The approval grain is category + dosage form,
// never brand, so a product is only ever matched to an approval through these two fields.
export interface Product {
  id: string
  name: string
  tga_category: string
  dosage_form: string
  pack: string
  schedule: "S4" | "S8"
}

// PROPOSED: prescriptions module (docs2/sdlc/07-script-queue/api.md)
export const SCRIPT_STATES = [
  "AWAITING_REVIEW",
  "SIGNED",
  "SENT",
  "BLOCKED",
  "REQUIRES_RECONCILIATION",
  "CANCELLED",
] as const
export type ScriptState = (typeof SCRIPT_STATES)[number]

export interface Script {
  id: string
  patient_id: string
  patient_name: string
  product_id: string
  product_name: string
  tga_category: string
  dosage_form: string
  quantity: string
  repeats: number
  directions: string
  triage_outcome: string | null
  conventional_therapy: string | null
  state: ScriptState
  drafted_by: string
  drafted_by_name: string
  prescriber_id: string
  prescriber_name: string
  date_of_service: string
  created_at: string
  signed_at: string | null
  sent_at: string | null
  escript_token: string | null
  pharmacy: string | null
  /** The latest gate decision, when one was made. */
  gate: TgaMatchResponse | null
}

export interface ScriptDraft {
  patient_id: string
  patient_name: string
  product_id: string
  quantity: string
  repeats: number
  directions: string
  triage_outcome: string
  conventional_therapy: string
  prescriber_id: string
  date_of_service: string
}

// PROPOSED: dashboard module, one round trip for the Today page.
export interface TodaySummary {
  date: string
  appointments: Appointment[]
  scripts_awaiting: Script[]
  scripts_blocked: number
  approvals_expiring: Array<
    TgaApproval & { patient_name: string; days_left: number }
  >
  attention: Array<{ id: string; title: string; body: string; href: string }>
}

// PROPOSED: public booking (no auth; tenant resolved from the clinic slug server-side).
export interface PublicSlot {
  practitioner_id: string
  practitioner_name: string
  starts_at: string
  ends_at: string
}

export interface PublicBookingRequest {
  slot: PublicSlot
  type: AppointmentType
  given_name: string
  family_name: string
  date_of_birth: string
  email: string
  phone: string
  condition: string
  tried_conventional: boolean
  conventional_detail: string
  consent: boolean
}
