import { uuid } from "@/data/preview/seed"
import { clinicInstant, plusMinutes } from "@/data/preview/time"
import {
  APPOINTMENT_TYPES,
  type Appointment,
  type AppointmentType,
  type PublicBookingRequest,
  type PublicSlot,
} from "@/data/types"
import { addDays, clinicToday } from "@/lib/format"
import { Refusal } from "@/lib/http"

/**
 * Public self-booking: PREVIEW ONLY. The proposed unauthenticated endpoints
 * (`GET /public/{clinic_slug}/slots`, `POST /public/{clinic_slug}/bookings`, rate-limited, tenant
 * resolved from the slug on the server, never from the client) are in
 * docs2/sdlc/04-calendar-and-booking/api.md.
 *
 * Without a backend there is no shared store between the public page and the clinic, so a preview
 * booking is held in this tab's sessionStorage and merged into the staff calendar when a staff
 * member signs in on the same tab.
 */
const PENDING_KEY = "clinic-os.preview.public-bookings"

const ROSTER = [
  { id: "prac-dunn", name: "Claire Dunn, RN", role: "NURSE" },
  { id: "prac-yates", name: "Ben Yates, RN", role: "NURSE" },
  { id: "prac-whitfield", name: "Dr James Whitfield", role: "DOCTOR" },
  { id: "prac-nair", name: "Dr Priya Nair", role: "DOCTOR" },
] as const

const SESSION_TIMES = [
  "09:00",
  "09:30",
  "10:15",
  "11:00",
  "13:30",
  "14:15",
  "15:00",
  "16:15",
]

const readPending = (): Appointment[] => {
  try {
    return JSON.parse(
      window.sessionStorage.getItem(PENDING_KEY) ?? "[]",
    ) as Appointment[]
  } catch {
    return []
  }
}

/** Hand pending public bookings to the staff preview store, once. */
export const takePendingPublicBookings = (): Appointment[] => {
  const pending = readPending()
  try {
    window.sessionStorage.removeItem(PENDING_KEY)
  } catch {
    // nothing to clear
  }
  return pending
}

/** A deterministic pseudo-random "already taken" pattern, so slot grids look like a real clinic. */
const taken = (key: string) => {
  let h = 0
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) | 0
  return Math.abs(h) % 3 === 0
}

export const bookingRepo = {
  slots: async (
    type: AppointmentType,
    fromDate = clinicToday(),
  ): Promise<PublicSlot[]> => {
    const { role, minutes } = APPOINTMENT_TYPES[type]
    const booked = readPending()
    const slots: PublicSlot[] = []
    for (let d = 1; d <= 14; d++) {
      const date = addDays(fromDate, d)
      const weekday = new Date(`${date}T12:00:00Z`).getUTCDay()
      if (weekday === 0 || weekday === 6) continue
      for (const prac of ROSTER.filter((p) => p.role === role))
        for (const t of SESSION_TIMES) {
          const starts = clinicInstant(date, t)
          if (taken(`${prac.id}${starts}`)) continue
          if (
            booked.some(
              (b) => b.practitioner_id === prac.id && b.starts_at === starts,
            )
          )
            continue
          slots.push({
            practitioner_id: prac.id,
            practitioner_name: prac.name,
            starts_at: starts,
            ends_at: plusMinutes(starts, minutes),
          })
        }
    }
    return slots
  },

  book: async (req: PublicBookingRequest): Promise<{ reference: string }> => {
    if (!req.consent)
      throw new Refusal(
        "CONSENT_REQUIRED",
        "Please agree to the privacy collection notice.",
      )
    const pending = readPending()
    if (
      pending.some(
        (b) =>
          b.practitioner_id === req.slot.practitioner_id &&
          b.starts_at === req.slot.starts_at,
      )
    )
      throw new Refusal(
        "SLOT_TAKEN",
        "Someone just booked that time. Please choose another.",
      )
    const reference = `BK-${uuid().slice(0, 6).toUpperCase()}`
    pending.push({
      id: uuid(),
      patient_id: `intake-${reference}`,
      patient_name: `${req.given_name.trim()} ${req.family_name.trim()}`,
      practitioner_id: req.slot.practitioner_id,
      type: req.type,
      status: "BOOKED",
      starts_at: req.slot.starts_at,
      ends_at: req.slot.ends_at,
      source: "PUBLIC_BOOKING",
      created_at: new Date().toISOString(),
    })
    try {
      window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending))
    } catch {
      // The confirmation still shows; the booking just won't reach the staff preview.
    }
    return { reference }
  },
}

export const clinicNameFromSlug = (slug: string) =>
  slug
    .split("-")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")
