/**
 * Which backend each feature reads from.
 *
 * `api`: the FastAPI backend serves it, and it is the source of truth.
 * `preview`: the backend module is not merged yet. The feature runs against an in-browser preview
 * store (src/data/preview) that implements the same repository interface and the same contract the
 * backend module documents. Every preview screen says so on the page (PreviewBanner), so preview data
 * is never mistaken for clinical data.
 *
 * Flip a feature to `api` here (or with VITE_API_FEATURES=a,b at build time) once its backend module
 * lands. The interface each one must satisfy is in docs2/sdlc/<feature>/api.md.
 */
export type Capability =
  | "patients"
  | "audit"
  | "clinicalRecords"
  | "tgaApprovals"
  | "appointments"
  | "prescriptions"
  | "dashboard"
  | "publicBooking"

type Source = "api" | "preview"

const DEFAULTS: Record<Capability, Source> = {
  patients: "api",
  audit: "api",
  clinicalRecords: "api",
  // The practice-wide register (GET /tga-approvals), the per-patient tab and every write are live.
  tgaApprovals: "api",
  // backend/app/modules/appointments (docs2/sdlc/04-calendar-and-booking/api.md).
  appointments: "api",
  publicBooking: "api",
  // Live: the script queue, signing and dispatch (the outbox; no pharmacy transport exists yet).
  prescriptions: "api",
  // No backend module yet; contract proposed in docs2/sdlc/08-today.
  dashboard: "preview",
}

const overrides = new Set(
  String(import.meta.env.VITE_API_FEATURES ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
)

export const sourceOf = (capability: Capability): Source =>
  overrides.has(capability) ? "api" : DEFAULTS[capability]

export const isPreview = (capability: Capability) =>
  sourceOf(capability) === "preview"
