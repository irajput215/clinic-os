# TGA approvals: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Whoever records can't verify (four-eyes refusal shown) | `tests/safety-gate.spec.ts` |
| e2e | **The letter's end date is sent unchanged and shown as printed (D-006 boundary)** | `tests/safety-gate.spec.ts` |
| manual (recorded) | Wrong reference at verify is refused; the right one activates and leaves Needs action | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
