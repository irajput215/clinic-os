# Script queue and safety gate: test plan

| Level | Case | Where |
|---|---|---|
| e2e | A script with no covering approval: gate blocked, password and Sign disabled | `tests/safety-gate.spec.ts` |
| e2e | A covered script: wrong password refused by the server; right password signs, and it appears as sent with an EVQ token | `tests/safety-gate.spec.ts` |
| manual (recorded) | Badge counts update live after signing (regression for a stale-reference bug fixed in the preview store) | - |
| backend (when built) | Every negative reason code at sign and at dispatch; idempotent dispatch; timeout gives REQUIRES_RECONCILIATION | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
