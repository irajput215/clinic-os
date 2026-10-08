# TGA approvals: test plan

| Level | Case | Where |
|---|---|---|
| e2e | Whoever records can't verify (four-eyes refusal shown) | `tests/safety-gate.spec.ts` |
| e2e | **The letter's end date is sent unchanged and shown as printed (D-006 boundary)** | `tests/safety-gate.spec.ts` |
| e2e | Record on the patient tab, four-eyes refusal, revoke with a reason code; after a reload the API's state shows, and the Overview has no active approval; no Preview banner | `tests/approvals.spec.ts` |
| e2e | The register lists an approval recorded from it under Needs action (one `state=PENDING&expiring_within_days=30` read), moves it between filters by URL, revokes it into Expired & revoked, links to the patient tab, and Back restores the filter; no tenant or patient id in the register URL; no Preview banner | `tests/approvals.spec.ts` |
| e2e | At 390px the register never scrolls the page sideways | `tests/approvals.spec.ts` |
| api | Register denials first: `401`, `403 PERMISSION_NOT_HELD` (audited), another tenant sees nothing, a client `tenant_id` is ignored and audited, malformed filters and forged cursors `422` | `backend/tests/tga/test_register.py` |
| api | Register success: state and expiring selectors and their union, the last-covered-day boundary, keyset pages without skips or repeats, practice totals, patient names, one audited read per page; per-patient list and detail reads audited, refusals included | `backend/tests/tga/test_register.py` |
| manual (recorded) | Wrong reference at verify is refused; the right one activates and leaves Needs action. Not automatable yet: a successful verify needs a second clinician in the tenant, and no API adds staff to an existing organisation | - |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
