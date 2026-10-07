import { CLINIC_TIMEZONE } from "@/lib/format"

/** The clinic timezone's UTC offset on a given date, in minutes (`+660` for AEDT). */
const offsetMinutes = (isoDate: string): number => {
  const probe = new Date(`${isoDate}T12:00:00Z`)
  const name =
    new Intl.DateTimeFormat("en-US", {
      timeZone: CLINIC_TIMEZONE,
      timeZoneName: "longOffset",
    })
      .formatToParts(probe)
      .find((p) => p.type === "timeZoneName")?.value ?? "GMT+10:00"
  const match = /GMT([+-])(\d{2}):(\d{2})/.exec(name)
  if (!match) return 600
  const sign = match[1] === "-" ? -1 : 1
  return sign * (Number(match[2]) * 60 + Number(match[3]))
}

/** `2026-10-06` + `09:30` in the clinic's timezone → an ISO instant. */
export const clinicInstant = (isoDate: string, hhmm: string): string => {
  const [h, m] = hhmm.split(":").map(Number)
  const utcMinutes = h * 60 + m - offsetMinutes(isoDate)
  const base = Date.parse(`${isoDate}T00:00:00Z`)
  return new Date(base + utcMinutes * 60_000).toISOString()
}

export const plusMinutes = (iso: string, minutes: number) =>
  new Date(Date.parse(iso) + minutes * 60_000).toISOString()

/** Minutes since midnight in the clinic's timezone. */
export const clinicMinutesOfDay = (iso: string): number => {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: CLINIC_TIMEZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(iso))
  const h = Number(parts.find((p) => p.type === "hour")?.value ?? 0) % 24
  const m = Number(parts.find((p) => p.type === "minute")?.value ?? 0)
  return h * 60 + m
}

export const clinicDateOf = (iso: string): string =>
  new Intl.DateTimeFormat("en-CA", { timeZone: CLINIC_TIMEZONE }).format(
    new Date(iso),
  )
