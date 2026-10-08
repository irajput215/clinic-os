# Today: test plan

| Level | Case | Where |
|---|---|---|
| backend | No session is `401`; the owner sees today's bookings only (not yesterday's or tomorrow's), counts by status, practitioner names, the script counts, the live gate on each actionable script, pending and expiring approvals | `backend/tests/dashboard/test_today.py` |
| backend | An approval lapsing in 31 days is not expiring, one lapsing in 30 is; the script card is bounded to 8 | same |
| backend | Reception gets `withheld: ["scripts"]`, pharmacy `["scripts", "approvals"]`, no role all three, with `200` | same |
| backend | The approvals section writes one `tga_approval.read` with the register's filter and the row count; a withheld section writes nothing | same |
| backend | Another organisation's bookings, scripts and approvals never appear; a `tenant_id` query parameter is ignored and recorded as `CLIENT_TENANT_ID_IGNORED` | same |
| backend | The clinic day follows Sydney through the end of daylight saving (a 25-hour day) | same |
| e2e | A booking, a blocked draft and an approval ending in 10 days, made through the API, show in the schedule, the staging queue ("Blocked · Wrong category"), the renewals table and needs attention; the page makes one dashboard request; no Preview banner; the renewal tile opens "Needs action"; a schedule row opens the patient | `frontend/tests/today.spec.ts` |
| manual (recorded) | No wrapping at 1200 px; stacks at 390 px | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
