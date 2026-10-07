import type {
  ApprovalState,
  MatchReason,
  TgaApproval,
  TgaMatchResponse,
} from "@/data/types"

/**
 * PREVIEW STAND-IN for `POST /api/v1/tga-approvals/match` (tga_approvals/service.py `match`).
 *
 * Only the Today page's preview sample still uses it (src/data/dashboard.ts), until
 * `GET /dashboard/today` lands. The script queue reads the gate from the prescriptions API. It is not
 * a security control: the server decides at sign and at dispatch.
 *
 * Semantics mirrored from the backend:
 * - the grain is (patient, TGA category, dosage form);
 * - the window is half-open `[valid_from, valid_to)` and evaluated at the date of service, never "now";
 * - a non-ACTIVE row refuses with a reason named after its state, before dates are considered;
 * - with no row at the grain, the nearest miss explains why (category, then dosage form).
 */
const STATE_REASONS: Partial<Record<ApprovalState, MatchReason>> = {
  PENDING: "TGA_APPROVAL_PENDING_VERIFICATION",
  REVOKED: "TGA_APPROVAL_REVOKED",
  SUPERSEDED: "TGA_APPROVAL_SUPERSEDED",
  REJECTED: "TGA_APPROVAL_REJECTED",
  EXPIRED: "TGA_APPROVAL_EXPIRED",
}

export interface MatchQuery {
  patient_id: string
  tga_category: string
  dosage_form: string
  date_of_service: string
}

const refuse = (
  query: MatchQuery,
  reason: MatchReason,
  row: TgaApproval | null,
): TgaMatchResponse => ({
  matched: false,
  reason_code: reason,
  state: row?.state ?? null,
  approval_id: row?.id ?? null,
  validity_interval: row
    ? { valid_from: row.valid_from, valid_to: row.valid_to, bounds: "[)" }
    : null,
  date_of_service: query.date_of_service,
  evaluated_timezone: "Australia/Sydney",
})

export const previewMatch = (
  approvals: TgaApproval[],
  query: MatchQuery,
): TgaMatchResponse => {
  const forPatient = approvals.filter((a) => a.patient_id === query.patient_id)
  if (forPatient.length === 0)
    return refuse(query, "TGA_APPROVAL_NOT_FOUND", null)

  const atGrain = forPatient.filter(
    (a) =>
      a.tga_category === query.tga_category &&
      a.dosage_form === query.dosage_form,
  )
  if (atGrain.length === 0) {
    const sameCategory = forPatient.find(
      (a) => a.tga_category === query.tga_category,
    )
    return sameCategory
      ? refuse(query, "TGA_DOSAGE_FORM_MISMATCH", sameCategory)
      : refuse(query, "TGA_CATEGORY_MISMATCH", forPatient[0])
  }

  const covering = atGrain.find(
    (a) =>
      a.state === "ACTIVE" &&
      a.valid_from <= query.date_of_service &&
      query.date_of_service < a.valid_to,
  )
  if (covering)
    return {
      matched: true,
      reason_code: null,
      state: covering.state,
      approval_id: covering.id,
      validity_interval: {
        valid_from: covering.valid_from,
        valid_to: covering.valid_to,
        bounds: "[)",
      },
      date_of_service: query.date_of_service,
      evaluated_timezone: "Australia/Sydney",
    }

  // Explain the refusal from the most relevant row: an ACTIVE one first (a date problem), then the
  // most recently created.
  const ranked = [...atGrain].sort(
    (a, b) =>
      Number(b.state === "ACTIVE") - Number(a.state === "ACTIVE") ||
      b.created_at.localeCompare(a.created_at),
  )
  const row = ranked[0]
  const byState = STATE_REASONS[row.state]
  if (row.state !== "ACTIVE" && byState) return refuse(query, byState, row)
  return query.date_of_service < row.valid_from
    ? refuse(query, "TGA_APPROVAL_NOT_YET_EFFECTIVE", row)
    : refuse(query, "TGA_APPROVAL_EXPIRED", row)
}
