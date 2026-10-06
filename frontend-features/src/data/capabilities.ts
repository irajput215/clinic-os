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
  // In flight on feat/clinical-records and feat/tga-approvals-engine; API adapters are ready.
  clinicalRecords: "preview",
  tgaApprovals: "preview",
  // No backend module yet; contracts proposed in docs2/sdlc.
  appointments: "preview",
  prescriptions: "preview",
  dashboard: "preview",
  publicBooking: "preview",
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
