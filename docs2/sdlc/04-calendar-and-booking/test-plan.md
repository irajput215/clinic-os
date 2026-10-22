# Calendar and booking: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Book a slot; a second booking at the same time for the same practitioner is refused with the clash named | `tests/calendar-and-booking.spec.ts` |
| e2e | Public booking: validation, then details, slot, confirmation with `BK-` reference; it then appears in the clinic's week view | `tests/calendar-and-booking.spec.ts` |
| e2e | An unknown clinic slug shows "This booking page isn't available" | `tests/calendar-and-booking.spec.ts` |
| backend | Exclusion constraint refuses overlap at the DB level; trigger and service agree on R4; RLS isolation and fail-closed; app role cannot delete; denials (401, 403, cross-tenant 404); `tenant_id` ignored and audited | `backend/tests/appointments/` |
| backend | Public routes: uniform 404, slots by role/hours/days, settings override, create-or-match without disclosure, `SLOT_TAKEN`, `SLOT_NOT_OFFERED`, 18+, minimal PHI, JSON only, per-address and per-email limits, nothing in logs | `backend/tests/appointments/test_public_booking.py` |

| e2e | The owner changes the hours and slot length in Settings > Clinic and the booking page offers exactly the new slots; a Doctor has no control and is refused | `tests/clinic-hours.spec.ts` |
| e2e | A public booking produces a confirmation email (Mailpit) with the clinic name, time and reference and nothing clinical | `tests/clinic-hours.spec.ts` |
| backend | Settings: deny paths (401, 403 audited, no organisation, `tenant_id` ignored and audited), validation (open before close, 5-minute marks, span at least one slot, allowed slot lengths, one row per day, at least one open day), audit on the change's transaction, slots and the calendar follow the settings, outside-hours count | `backend/tests/appointments/test_settings.py` |
| backend | Notifications: rows only with email configured, confirmation sent after commit, reminder due 24 h before, never twice (unique row, at-most-once claim, concurrent runs), cancelled/started/no-email skipped, SMTP failure retried then failed, content carries nothing clinical, nothing in logs, the internal endpoint's token and fail-closed answers | `backend/tests/appointments/test_notifications.py` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
