import { queryOptions } from "@tanstack/react-query"
import { AppointmentsService } from "@/client"
import type {
  Appointment,
  AppointmentStatus,
  AppointmentType,
  Practitioner,
} from "@/data/types"
import { clinicInstant } from "@/lib/clinic-time"
import { addDays } from "@/lib/format"

/**
 * Appointments, served by backend/app/modules/appointments/router.py:
 *   GET  /practitioners                          GET /appointments?from=&to=&practitioner_id=
 *   POST /appointments                           POST /appointments/{id}/status
 *   GET  /patients/{id}/appointments
 * A double-booking is refused by a GiST exclusion constraint in the database (`409
 * APPOINTMENT_OVERLAP`, naming the clashing time); a status change outside R4's machine is `409
 * ILLEGAL_STATE_TRANSITION`. Both arrive as RFC 7807 `detail.code` and are shown in the dialog.
 */
export interface NewAppointment {
  patient_id: string
  practitioner_id: string
  type: AppointmentType
  starts_at: string
}

export const appointmentsRepo = {
  practitioners: async (): Promise<Practitioner[]> =>
    (await AppointmentsService.listPractitioners()).data,

  /**
   * Appointments starting on any of the given clinic dates (consecutive, as the day and week views
   * ask), as one `[first 00:00, day after last 00:00)` window in Australia/Sydney.
   */
  listForDates: async (dates: string[]): Promise<Appointment[]> => {
    const sorted = [...dates].sort()
    return (
      await AppointmentsService.listAppointments({
        query: {
          from: clinicInstant(sorted[0], "00:00"),
          to: clinicInstant(addDays(sorted[sorted.length - 1], 1), "00:00"),
        },
      })
    ).data
  },

  listForPatient: async (patientId: string): Promise<Appointment[]> =>
    (
      await AppointmentsService.listPatientAppointments({
        path: { patient_id: patientId },
      })
    ).data,

  create: async (input: NewAppointment): Promise<Appointment> =>
    (await AppointmentsService.createAppointment({ body: input })).data,

  setStatus: async (
    id: string,
    status: AppointmentStatus,
  ): Promise<Appointment> =>
    (
      await AppointmentsService.changeAppointmentStatus({
        path: { appointment_id: id },
        body: { status },
      })
    ).data,
}

export const practitionersQuery = queryOptions({
  queryKey: ["practitioners"],
  queryFn: appointmentsRepo.practitioners,
  staleTime: 5 * 60_000,
})

export const appointmentsForDatesQuery = (dates: string[]) =>
  queryOptions({
    queryKey: ["appointments", "dates", dates.join(",")],
    queryFn: () => appointmentsRepo.listForDates(dates),
    staleTime: 15_000,
  })

export const patientAppointmentsQuery = (patientId: string) =>
  queryOptions({
    queryKey: ["appointments", "patient", patientId],
    queryFn: () => appointmentsRepo.listForPatient(patientId),
    staleTime: 15_000,
  })

export const STATUS_LABEL: Record<AppointmentStatus, string> = {
  BOOKED: "Booked",
  CONFIRMED: "Confirmed",
  ARRIVED: "Arrived",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
  NO_SHOW: "No-show",
}
