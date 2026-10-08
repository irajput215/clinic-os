import { PublicBookingService } from "@/client"
import type { PublicBookingRequest } from "@/client/types.gen"
import type { AppointmentType, PublicSlot } from "@/data/types"

/**
 * Public self-booking, served by backend/app/modules/appointments/router.py without a session:
 *   GET  /public/{clinic_slug}/slots?type=     POST /public/{clinic_slug}/bookings
 * The server resolves the clinic from the slug (an unknown or inactive clinic is `404
 * CLINIC_NOT_FOUND`), rate-limits per address and per email, and answers the same `{reference}`
 * whether the patient was new or already known. `409 SLOT_TAKEN` when someone booked the time first.
 *
 * Only what a booking needs is sent: the slot, name, date of birth, contact details and consent.
 * The page's eligibility questions decide whether to offer a booking and never leave the browser.
 */
export const bookingRepo = {
  slots: async (
    clinicSlug: string,
    type: AppointmentType,
  ): Promise<PublicSlot[]> =>
    (
      await PublicBookingService.bookingListPublicSlots({
        path: { clinic_slug: clinicSlug },
        query: { type },
      })
    ).data,

  book: async (
    clinicSlug: string,
    body: PublicBookingRequest,
  ): Promise<{ reference: string }> =>
    (
      await PublicBookingService.bookingCreatePublicBooking({
        path: { clinic_slug: clinicSlug },
        body,
      })
    ).data,
}

/**
 * The clinic's name as the page shows it: derived from its routing slug, which is the only public
 * identity a clinic has today (its legal name is not public data).
 */
export const clinicNameFromSlug = (slug: string) =>
  slug
    .split("-")
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ")
