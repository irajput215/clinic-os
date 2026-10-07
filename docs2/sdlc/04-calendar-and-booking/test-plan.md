# Calendar and booking: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Book a slot; a second booking at the same time for the same practitioner is refused with the clash named | `tests/calendar-and-booking.spec.ts` |
| e2e | Public booking: validation, then details, slot, confirmation with `BK-` reference; it then appears in the clinic's week view | `tests/calendar-and-booking.spec.ts` |
| e2e | An unknown clinic slug shows "This booking page isn't available" | `tests/calendar-and-booking.spec.ts` |
| backend | Exclusion constraint refuses overlap at the DB level; trigger and service agree on R4; RLS isolation and fail-closed; app role cannot delete; denials (401, 403, cross-tenant 404); `tenant_id` ignored and audited | `backend/tests/appointments/` |
| backend | Public routes: uniform 404, slots by role/hours/days, settings override, create-or-match without disclosure, `SLOT_TAKEN`, `SLOT_NOT_OFFERED`, 18+, minimal PHI, JSON only, per-address and per-email limits, nothing in logs | `backend/tests/appointments/test_public_booking.py` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
