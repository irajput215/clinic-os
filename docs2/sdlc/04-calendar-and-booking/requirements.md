# Calendar and booking: requirements

**For:** Reception and clinicians managing the day; new patients booking themselves.

## User stories

- As reception, I see every practitioner's day side by side and book into a free slot with one click.
- As reception, I move an appointment through confirmed, arrived and completed.
- As a new patient, I book a free nurse triage or a doctor consult online, after a short eligibility questionnaire.

## Functional requirements

- R1 Day view: one column per practitioner, 08:00 to 18:00 in 15-minute slots, a now line, status-coloured blocks. Week view: Monday to Friday lists.
- R2 Appointment types: nurse triage (15 min, nurse), initial consult (30 min, doctor), follow-up (15 min, doctor). The type must match the practitioner's role.
- R3 A practitioner can't be double-booked. The refusal names the clash.
- R4 Status machine: BOOKED to CONFIRMED / ARRIVED / CANCELLED / NO_SHOW; CONFIRMED to ARRIVED / CANCELLED / NO_SHOW; ARRIVED to COMPLETED. Terminal states don't change.
- R5 Public booking at `/book/<clinic-slug>` without sign-in: visit type, then questionnaire and details (18+, AU mobile, consent to the APP 5 collection notice), then a slot. It returns a reference.
- R6 A public booking appears on the clinic calendar, marked as from the booking page, for intake.
- R7 All times are Australia/Sydney.
- R8 (2026-10-08) The Practice Owner sets the clinic's opening hours per weekday (or closes a day) and the slot length in Settings > Clinic. The public booking page offers only times inside those hours, on that slot grid; the calendar's day view follows the same hours and grid. Others are not offered the control and are refused by the server.
- R9 (2026-10-08) A booking, public or by staff, emails the patient a confirmation, and a reminder 24 hours before, when outgoing email is configured: the clinic's display name, the date and time, the reference and how to change it, and nothing clinical. A cancelled booking is never reminded, and no booking is reminded twice.

## Non-functional

- Slot grid fits 5 practitioners at 1200 px and scrolls horizontally inside its card on narrower screens.

## Out of scope (this phase)

- Rostering (per-practitioner availability). Clinic-wide opening hours are R8.
- Upfront payment (Tyro).
- SMS confirmations.
