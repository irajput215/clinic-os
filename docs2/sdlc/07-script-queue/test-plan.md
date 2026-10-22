# Script queue and safety gate: test plan

| Level | Case | Where |
|---|---|---|
| e2e | A script with no covering approval: gate blocked, password and Sign disabled | `tests/safety-gate.spec.ts` |
| e2e | A covered script: wrong password refused by the server; right password signs, and it appears as sent with an EVQ token | `tests/safety-gate.spec.ts` |
| manual (recorded) | Badge counts update live after signing | - |
| backend (when built) | Every negative reason code at sign and at dispatch; idempotent dispatch; timeout gives REQUIRES_RECONCILIATION | - |
| api | D-010: each new route refuses without the permission (`403`), across tenants (`404`), off the care team (`403`), for someone else's script (`403`), in the wrong state (`409`) and on an invalid body (`422`); then edit, cancel, addendum (original unchanged, replay, one per original), history and read, with their audit events; the trigger freezes the addendum link and the reason | `backend/tests/prescriptions/test_draft_cancel_addendum.py` |
| e2e | A draft is edited, cancelled with a reason and its history shows both; a signed script cannot be edited and is amended by a new draft | `tests/script-corrections.spec.ts` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
