import { AxiosError } from "axios"

/**
 * A refusal decided in the browser, carrying a machine-readable `code` like the API's `detail.code`,
 * so screens handle both identically. Raised by the preview store (src/data/preview) and its
 * repositories.
 */
export class Refusal extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = "Refusal"
  }
}

/** The HTTP status of a failed API call, or `undefined` when it was not an HTTP failure. */
export const httpStatus = (error: unknown): number | undefined =>
  error instanceof AxiosError ? error.response?.status : undefined

/**
 * True when the API answered "there is no such record for you".
 *
 * The API answers `404` both for a record that does not exist and for one that belongs to another
 * organisation, so the response cannot confirm that someone else's record exists. A malformed id in
 * the URL is rejected by path validation and comes back `422`. Both mean "nothing to show".
 */
export const isNotFound = (error: unknown): boolean => {
  const status = httpStatus(error)
  return status === 404 || status === 422
}

/** `403`: the session is valid and this identity may not do this. Never a reason to sign out. */
export const isForbidden = (error: unknown): boolean =>
  httpStatus(error) === 403

/**
 * Retry only what can change on its own: a request that never reached the API, or a `5xx`.
 * A `4xx` is the API's final answer; retrying it only puts a spinner in front of a decided state.
 */
export const retryTransient = (
  failureCount: number,
  error: unknown,
): boolean => {
  // A refusal is decided, not transient: retrying it only delays the answer.
  if (error instanceof Refusal) return false
  const status = httpStatus(error)
  if (status !== undefined && status >= 400 && status < 500) return false
  return failureCount < 3
}

const problemBody = (error: unknown): Record<string, unknown> | undefined => {
  if (!(error instanceof AxiosError)) return undefined
  const data: unknown = error.response?.data
  return typeof data === "object" && data !== null
    ? (data as Record<string, unknown>)
    : undefined
}

/** The API's own sentence for a refusal: `detail.message`, a string `detail`, or the RFC `title`. */
export const apiErrorMessage = (error: unknown): string | undefined => {
  const body = problemBody(error)
  const detail = body?.detail
  if (typeof detail === "string") return detail
  if (typeof detail === "object" && detail !== null) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string") return message
  }
  return typeof body?.title === "string" ? body.title : undefined
}

/**
 * The machine-readable code of an API refusal: `detail.code` for a decided refusal, or the custom
 * `type` of the first validation error (the API names its own validators, e.g.
 * `ERR_WINDOW_EXCEEDS_MAX_DURATION`; Pydantic's built-in types are lower case and are not codes).
 */
export const refusalCode = (error: unknown): string | undefined => {
  if (error instanceof Refusal) return error.code
  const detail = problemBody(error)?.detail
  if (Array.isArray(detail)) {
    const type = (detail[0] as { type?: unknown } | undefined)?.type
    return typeof type === "string" && /^[A-Z][A-Z0-9_]+$/.test(type)
      ? type
      : undefined
  }
  if (typeof detail === "object" && detail !== null) {
    const code = (detail as { code?: unknown }).code
    if (typeof code === "string") return code
  }
  return undefined
}

/**
 * Plain sentences for the refusal codes the API documents, so a clinician reads what to do next
 * rather than the server's internal phrasing. A code not listed here falls back to the API's own
 * `detail.message`.
 */
const REFUSAL_SENTENCES: Record<string, string> = {
  // tga_approvals (docs2/sdlc/05-approvals)
  VERIFIER_CANNOT_BE_CREATOR:
    "You entered this approval, so a second clinician must verify it.",
  TGA_APPLICATION_NUMBER_MISMATCH:
    "That reference doesn't match the approval. Re-enter it from the TGA letter.",
  TGA_OVERLAPPING_ACTIVE_APPROVAL:
    "An active approval already covers these dates for this category and form. Supersede it instead.",
  DUPLICATE_APPROVAL_GRAIN:
    "This approval is already on file for this patient, category, dosage form and dates.",
  ILLEGAL_STATE_TRANSITION:
    "This can't be changed that way any more. Refresh to see its current state.",
  ERR_WINDOW_NOT_FORWARD: "The end date must be after the start date.",
  ERR_WINDOW_EXCEEDS_MAX_DURATION:
    "An approval can't be valid for more than two years.",
  // clinical_records (docs2/sdlc/03-consult-notes)
  NOTE_ALREADY_SIGNED: "This note is already signed. Add an amendment instead.",
  SIGN_NOT_VERSION_AUTHOR:
    "Only the clinician who wrote this version can sign it.",
  AMENDMENT_REASON_REQUIRED: "Say why the note is being amended.",
  VERSION_CONFLICT:
    "Someone else amended this note at the same time. Refresh and try again.",
  // prescriptions and step-up (docs2/sdlc/07-script-queue)
  STEP_UP_FAILED: "That password isn't right. Re-enter it to continue.",
  STEP_UP_REQUIRED:
    "Your re-entered password expired before it was used. Enter it again.",
  NOT_PRESCRIBER_OF_RECORD:
    "Only the assigned prescriber can sign this script.",
  PRESCRIBER_NOT_AUTHORIZED:
    "Choose a doctor in your practice who can sign prescriptions.",
  INVALID_STATE_TRANSITION:
    "This script has already moved on. Refresh to see where it is now.",
  PATIENT_NOT_FOUND: "That patient isn't available.",
  TGA_APPROVAL_NOT_FOUND:
    "Blocked by the safety gate: no TGA approval on file for this patient. Nothing was signed or sent.",
  TGA_CATEGORY_MISMATCH:
    "Blocked by the safety gate: the approval is for a different TGA category. Nothing was signed or sent.",
  TGA_DOSAGE_FORM_MISMATCH:
    "Blocked by the safety gate: the approval is for a different dosage form. Nothing was signed or sent.",
  TGA_APPROVAL_EXPIRED:
    "Blocked by the safety gate: the approval had expired on the date of service. Nothing was signed or sent.",
  TGA_APPROVAL_NOT_YET_EFFECTIVE:
    "Blocked by the safety gate: the approval had not started on the date of service. Nothing was signed or sent.",
  TGA_APPROVAL_REVOKED:
    "Blocked by the safety gate: the approval was revoked. Nothing was signed or sent.",
  TGA_APPROVAL_PENDING_VERIFICATION:
    "Blocked by the safety gate: the approval still needs a second clinician to verify it. Nothing was signed or sent.",
  TGA_APPROVAL_SUPERSEDED:
    "Blocked by the safety gate: the approval was replaced by a newer grant. Nothing was signed or sent.",
  TGA_APPROVAL_REJECTED:
    "Blocked by the safety gate: the approval was rejected at verification. Nothing was signed or sent.",
}

/**
 * A `422`'s field-level messages, keyed by the body or path field the API named. The API's
 * validation envelope carries only `type`, `loc` and `msg` (never the submitted value), so these are
 * safe to show next to the field.
 */
export const validationMessages = (error: unknown): Record<string, string> => {
  if (httpStatus(error) !== 422) return {}
  const detail = problemBody(error)?.detail
  if (!Array.isArray(detail)) return {}
  const messages: Record<string, string> = {}
  for (const issue of detail) {
    const loc: unknown = issue?.loc
    const msg: unknown = issue?.msg
    if (!Array.isArray(loc) || typeof msg !== "string") continue
    const field = loc[1]
    if (typeof field === "string" && !(field in messages)) messages[field] = msg
  }
  return messages
}

/** The correlation handle the API puts on every problem body, for a support conversation. */
export const apiRequestId = (error: unknown): string | undefined => {
  const id = problemBody(error)?.request_id
  return typeof id === "string" ? id : undefined
}

/** One sentence a person can act on, for any failure. Never echoes request data. */
export const describeError = (error: unknown): string => {
  if (error instanceof Refusal) return error.message
  const code = refusalCode(error)
  if (code && code in REFUSAL_SENTENCES) return REFUSAL_SENTENCES[code]
  const status = httpStatus(error)
  if (status === undefined)
    return "Can't reach Clinic OS right now. Check your connection and try again."
  if (status === 403) return "Your role doesn't allow this."
  if (status === 404) return "That record isn't available."
  if (status === 429) return "Too many attempts. Wait a minute, then try again."
  if (status >= 500)
    return "Something went wrong on our side. Nothing was changed; try again."
  return (
    apiErrorMessage(error) ??
    "That didn't work. Check the details and try again."
  )
}
