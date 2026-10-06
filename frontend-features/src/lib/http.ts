import { AxiosError } from "axios"

/**
 * A refusal raised in the browser by the preview store (src/data/preview), carrying the same
 * machine-readable `code` the API puts in `detail.code`, so screens handle both identically.
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
