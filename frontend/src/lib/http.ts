import { AxiosError } from "axios"

/** The HTTP status of a failed API call, or `undefined` when it was not an HTTP failure. */
export const httpStatus = (error: unknown): number | undefined =>
  error instanceof AxiosError ? error.response?.status : undefined

/**
 * True when the API answered "there is no such record for you".
 *
 * The patients API answers `404` both for a record that does not exist and for one that
 * belongs to another organisation — deliberately, so the response cannot confirm that
 * someone else's record exists (`backend/app/modules/patients/router.py`). A malformed id
 * in the URL is rejected by path validation before the service runs and comes back `422`.
 * Both mean "this screen has nothing to show", which is not an error state.
 */
export const isNotFound = (error: unknown): boolean => {
  const status = httpStatus(error)
  return status === 404 || status === 422
}

/**
 * Retry only what can change on its own: a request that never reached the API, or a `5xx`.
 *
 * A `4xx` is the API's final answer, and TanStack Query's default retries *every* failure
 * three times with exponential backoff — seven seconds of spinner in front of a state that
 * was already decided. That delay is what made a refused Patients tab feel slow on the way to
 * signing the user out.
 */
export const retryTransient = (
  failureCount: number,
  error: unknown,
): boolean => {
  const status = httpStatus(error)
  if (status !== undefined && status >= 400 && status < 500) return false
  return failureCount < 3
}

/**
 * The machine-readable reason code from the API's standard denial envelope
 * (`{ detail: { code, message } }`), which the policy layer and the route handlers both use.
 * `undefined` for a string detail or a network failure.
 */
export const apiErrorCode = (error: unknown): string | undefined => {
  if (!(error instanceof AxiosError)) return undefined
  const detail: unknown = error.response?.data?.detail
  if (typeof detail !== "object" || detail === null) return undefined
  const code = (detail as { code?: unknown }).code
  return typeof code === "string" ? code : undefined
}

/** The API's own message for a refusal: the envelope's `message`, or a bare `detail` string. */
export const apiErrorMessage = (error: unknown): string | undefined => {
  if (!(error instanceof AxiosError)) return undefined
  const detail: unknown = error.response?.data?.detail
  if (typeof detail === "string") return detail
  if (typeof detail === "object" && detail !== null) {
    const message = (detail as { message?: unknown }).message
    if (typeof message === "string") return message
  }
  return undefined
}
