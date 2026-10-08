/**
 * Formatting in the clinic's timezone. Clinical dates (service dates, approval windows) are
 * evaluated in Australia/Sydney by the backend, so the UI shows them in the same zone regardless of
 * where the browser is.
 */
export const CLINIC_TIMEZONE = "Australia/Sydney"
const LOCALE = "en-AU"

const fmt = (options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat(LOCALE, { timeZone: CLINIC_TIMEZONE, ...options })

const dayMonthYear = fmt({ day: "numeric", month: "short", year: "numeric" })
const weekdayLong = fmt({
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
})
const time24 = fmt({ hour: "2-digit", minute: "2-digit", hour12: false })
const dayMonth = fmt({ day: "numeric", month: "short" })
const dayMonthTime = fmt({
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
})

/** `2026-03-15` (a calendar date) → a Date at noon UTC, so no timezone can move it a day. */
const fromIsoDate = (iso: string) => new Date(`${iso}T12:00:00Z`)

export const formatDate = (iso: string) =>
  dayMonthYear.format(iso.length === 10 ? fromIsoDate(iso) : new Date(iso))
export const formatDayMonth = (iso: string) =>
  dayMonth.format(iso.length === 10 ? fromIsoDate(iso) : new Date(iso))
/** An instant, or a calendar date (`YYYY-MM-DD`) such as the server's clinic day. */
export const formatLongDay = (date: Date | string) =>
  weekdayLong.format(typeof date === "string" ? fromIsoDate(date) : date)
export const formatTime = (iso: string | Date) =>
  time24.format(typeof iso === "string" ? new Date(iso) : iso)
export const formatDayMonthTime = (iso: string) =>
  dayMonthTime.format(new Date(iso))

/** Today's calendar date in the clinic's timezone, as `YYYY-MM-DD`. */
export const clinicToday = (now: Date = new Date()): string =>
  new Intl.DateTimeFormat("en-CA", { timeZone: CLINIC_TIMEZONE }).format(now)

export const addDays = (isoDate: string, days: number): string => {
  const d = fromIsoDate(isoDate)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export const daysBetween = (fromIso: string, toIso: string): number =>
  Math.round(
    (fromIsoDate(toIso).getTime() - fromIsoDate(fromIso).getTime()) /
      86_400_000,
  )

/**
 * The last day an approval covers. The API stores the window half-open, `[valid_from, valid_to)`, as
 * D-006's interim fail-safe reading, so `valid_to` (the end date printed on the TGA letter) is itself
 * NOT covered and the last covered day is the day before (ADR-F003).
 */
export const lastCoveredDay = (validToExclusive: string) =>
  addDays(validToExclusive, -1)

export const age = (dateOfBirth: string, today = clinicToday()): number => {
  const [by, bm, bd] = dateOfBirth.split("-").map(Number)
  const [ty, tm, td] = today.split("-").map(Number)
  return ty - by - (tm < bm || (tm === bm && td < bd) ? 1 : 0)
}

/** A short, stable patient reference for display (`PT-1A2B3C`), derived from the record id. */
export const patientRef = (id: string) =>
  `PT-${id.replace(/-/g, "").slice(0, 6).toUpperCase()}`
