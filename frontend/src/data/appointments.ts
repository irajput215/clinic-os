import { queryOptions } from "@tanstack/react-query"
import { uuid } from "@/data/preview/seed"
import { readPreview, writePreview } from "@/data/preview/store"
import { clinicDateOf, plusMinutes } from "@/data/preview/time"
import {
  APPOINTMENT_TRANSITIONS,
  APPOINTMENT_TYPES,
  type Appointment,
  type AppointmentStatus,
  type AppointmentType,
  type Practitioner,
} from "@/data/types"
import { Refusal } from "@/lib/http"

/**
 * Appointments: PREVIEW ONLY. No backend module exists; the proposed contract (including the GiST
 * exclusion constraint that makes a double-booking impossible in the database) is
 * docs2/sdlc/04-calendar-and-booking/api.md. The preview enforces the same overlap and status rules
 * so the UI is built against the behaviour the API will have.
 */
export interface NewAppointment {
  patient_id: string
  patient_name: string
  practitioner_id: string
  type: AppointmentType
  starts_at: string
}

const overlaps = (a: { starts_at: string; ends_at: string }, b: Appointment) =>
  b.status !== "CANCELLED" &&
  b.status !== "NO_SHOW" &&
  a.starts_at < b.ends_at &&
  b.starts_at < a.ends_at

export const appointmentsRepo = {
  practitioners: async (): Promise<Practitioner[]> =>
    (await readPreview()).practitioners,

  /** Appointments whose start falls on any of the given clinic dates. */
  listForDates: async (dates: string[]): Promise<Appointment[]> => {
    const wanted = new Set(dates)
    return (await readPreview()).appointments
      .filter((a) => wanted.has(clinicDateOf(a.starts_at)))
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at))
  },

  listForPatient: async (patientId: string): Promise<Appointment[]> =>
    (await readPreview()).appointments
      .filter((a) => a.patient_id === patientId)
      .sort((a, b) => b.starts_at.localeCompare(a.starts_at)),

  create: (input: NewAppointment, source: Appointment["source"] = "STAFF") =>
    writePreview((s) => {
      const practitioner = s.practitioners.find(
        (p) => p.id === input.practitioner_id,
      )
      if (!practitioner)
        throw new Refusal(
          "PRACTITIONER_NOT_FOUND",
          "Choose who the appointment is with.",
        )
      const type = APPOINTMENT_TYPES[input.type]
      if (type.role !== practitioner.role)
        throw new Refusal(
          "TYPE_NOT_OFFERED",
          `${type.label} is booked with a ${type.role === "NURSE" ? "nurse" : "doctor"}.`,
        )
      const candidate = {
        starts_at: input.starts_at,
        ends_at: plusMinutes(input.starts_at, type.minutes),
      }
      const clash = s.appointments.find(
        (a) =>
          a.practitioner_id === input.practitioner_id && overlaps(candidate, a),
      )
      if (clash)
        throw new Refusal(
          "APPOINTMENT_OVERLAP",
          `${practitioner.name} already has ${clash.patient_name} at that time.`,
        )
      const appt: Appointment = {
        id: uuid(),
        ...input,
        ...candidate,
        status: "BOOKED",
        source,
        created_at: new Date().toISOString(),
      }
      s.appointments.push(appt)
      return appt
    }),

  setStatus: (id: string, status: AppointmentStatus) =>
    writePreview((s) => {
      const appt = s.appointments.find((a) => a.id === id)
      if (!appt)
        throw new Refusal("NOT_FOUND", "That appointment isn't available.")
      if (!APPOINTMENT_TRANSITIONS[appt.status].includes(status))
        throw new Refusal(
          "ILLEGAL_STATE_TRANSITION",
          `A ${appt.status.toLowerCase()} appointment can't be marked ${status.toLowerCase().replace("_", " ")}.`,
        )
      appt.status = status
      return appt
    }),
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
