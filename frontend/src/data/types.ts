/**
 * Domain types the generated client states more loosely than the backend enforces.
 *
 * Two kinds live here, and the comment on each says which:
 * - MIRROR: a vocabulary or shape copied from a backend module
 *   (backend/app/modules/<module>/{models,schemas,service}.py), where the generated type is only
 *   `string`. The backend file is named beside it, so a change there has one place to land here.
 * - GENERATED: an alias of the generated client's type, kept so screens import one name.
 *
 * Every feature reads the API (ADR-F006): no type here is a proposal waiting for a backend.
 */
import type {
  AppointmentRead,
  PublicSlot as GeneratedPublicSlot,
  PractitionerRead,
} from "@/client/types.gen"

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

// GENERATED: appointments module (backend/app/modules/appointments/schemas.py). A person who can be
// booked, resolved from users + roles server-side; a booking, half-open `[starts_at, ends_at)`.
export type Practitioner = PractitionerRead
export type Appointment = AppointmentRead
export type PublicSlot = GeneratedPublicSlot

// MIRROR: appointments/models.py APPOINTMENT_TYPES (R2). The server computes `ends_at` from it.
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
