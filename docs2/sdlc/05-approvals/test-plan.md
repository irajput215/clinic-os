# TGA approvals: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Whoever records can't verify (four-eyes refusal shown) | `tests/safety-gate.spec.ts` |
| e2e | **The letter's end date is sent unchanged and shown as printed (D-006 boundary)** | `tests/safety-gate.spec.ts` |
| e2e | Record on the patient tab, four-eyes refusal, revoke with a reason code; after a reload the API's state shows, and the Overview has no active approval; no Preview banner | `tests/approvals.spec.ts` |
| e2e | The register shows the refusal naming `GET /api/v1/tga-approvals`, with no filters, no rows, no Preview banner and no request to the missing route | `tests/approvals.spec.ts` |
| manual (recorded) | Wrong reference at verify is refused; the right one activates and leaves Needs action. Not automatable yet: a successful verify needs a second clinician in the tenant, and no API adds staff to an existing organisation | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
