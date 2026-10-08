import { queryOptions } from "@tanstack/react-query"
import { AppointmentsService } from "@/client"
import type {
  AppointmentSettingsRead,
  AppointmentSettingsSaved,
  AppointmentSettingsUpdate,
} from "@/client/types.gen"

/**
 * The clinic's opening hours and slot length (docs2/sdlc/04-calendar-and-booking/api.md, "Clinic
 * hours, slot length and booking emails"):
 *   GET /appointment-settings   any member (opening hours are PUBLIC)
 *   PUT /appointment-settings   `tenant:configure` (Practice Owner); `422` names the day it is about
 * Seven days, Monday first; a closed day has both times `null`. The calendar's day view and the
 * public booking page's slots follow them.
 */
export type ClinicHours = AppointmentSettingsRead
export type ClinicHoursSaved = AppointmentSettingsSaved
export type ClinicHoursUpdate = AppointmentSettingsUpdate

export const SLOT_MINUTES = [10, 15, 20, 30, 60] as const
export type SlotMinutes = (typeof SLOT_MINUTES)[number]

export const WEEKDAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const

export const clinicHoursQuery = queryOptions({
  queryKey: ["clinic-hours"],
  queryFn: async (): Promise<ClinicHours> =>
    (await AppointmentsService.readAppointmentSettings()).data,
  staleTime: 5 * 60_000,
})

export const saveClinicHours = async (
  body: ClinicHoursUpdate,
): Promise<ClinicHoursSaved> =>
  (await AppointmentsService.updateAppointmentSettings({ body })).data

/** `"09:30"` as minutes after midnight. */
export const minutesOf = (hhmm: string) =>
  Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
