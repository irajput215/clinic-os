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
