# Calendar and booking: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Book a slot; a second booking at the same time for the same practitioner is refused with the clash named | `tests/calendar-and-booking.spec.ts` |
| e2e | Public booking: validation, then details, slot, confirmation with `BK-` reference; it then appears in the clinic's week view | `tests/calendar-and-booking.spec.ts` |
| backend (when built) | Exclusion constraint refuses overlap at the DB level; RLS isolation; public endpoints never accept `tenant_id` | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
