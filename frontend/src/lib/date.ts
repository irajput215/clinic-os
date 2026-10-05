/**
 * Date display helpers.
 *
 * Patient dates arrive as date-only strings (`YYYY-MM-DD`, from the API's `date` fields)
 * and clinical metadata arrives as ISO timestamps (`created_at`, `updated_at`,
 * `deceased_at`). Both are formatted here so every screen renders them the same way, and
 * so a value is formatted the same way it is validated in the form schema.
 */

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/

const dateOnlyFormatter = new Intl.DateTimeFormat("en-AU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
})

const timestampFormatter = new Intl.DateTimeFormat("en-AU", {
  dateStyle: "medium",
  timeStyle: "short",
})

/**
 * A local-midnight `Date` for a calendar day given as parts.
 *
 * The year is applied with `setFullYear` because `new Date(year, ...)` and `Date.UTC` both
 * map a year of 0–99 onto 1900–1999, which would make `0001-01-01` an invalid date and
 * would format it as the wrong year.
 */
const localDate = (year: number, month: number, day: number): Date => {
  const date = new Date(0)
  date.setFullYear(year, month - 1, day)
  date.setHours(0, 0, 0, 0)
  return date
}

/**
 * True when `value` is a `YYYY-MM-DD` string naming a real calendar day.
 *
 * The parts are compared back against a constructed date, so `2025-02-30` and `2025-13-01`
 * are rejected instead of rolling over into the next month (which is what `new Date()`
 * does with an out-of-range value).
 */
export const isValidDateOnly = (value: string): boolean => {
  const match = DATE_ONLY.exec(value)
  if (!match) return false
  const [, year, month, day] = match
  const date = localDate(Number(year), Number(month), Number(day))
  return (
    date.getFullYear() === Number(year) &&
    date.getMonth() === Number(month) - 1 &&
    date.getDate() === Number(day)
  )
}

/**
 * The date part of a date or timestamp, as `YYYY-MM-DD`, for a `<input type="date">`.
 *
 * Returns `""` — not `null` — because that is the empty value of a date input, and it is
 * what the form schema expects.
 */
export const toDateOnly = (value: string | null | undefined): string => {
  if (!value) return ""
  const candidate = value.slice(0, 10)
  return isValidDateOnly(candidate) ? candidate : ""
}

/** Today as `YYYY-MM-DD` in the **browser's local** calendar. */
export const localToday = (): string => {
  const now = new Date()
  const month = `${now.getMonth() + 1}`.padStart(2, "0")
  const day = `${now.getDate()}`.padStart(2, "0")
  return `${now.getFullYear()}-${month}-${day}`
}

/**
 * Format a date-only string for display, or `null` when it is missing or not a date.
 *
 * The value is parsed from its parts rather than with `new Date(value)`: the JavaScript
 * date parser treats a date-only string as UTC midnight, which renders as the previous day
 * anywhere west of UTC.
 */
export const formatDateOnly = (
  value: string | null | undefined,
): string | null => {
  if (!value || !isValidDateOnly(value)) return null
  const [year, month, day] = value.split("-").map(Number)
  return dateOnlyFormatter.format(localDate(year, month, day))
}

/** Format an ISO timestamp for display, or `null` when it is missing or not a date. */
export const formatTimestamp = (
  value: string | null | undefined,
): string | null => {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : timestampFormatter.format(date)
}
