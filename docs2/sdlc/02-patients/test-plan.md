# Patients: test plan

| Level | Case | Where |
|---|---|---|
| e2e | The list shows API patients; the filter narrows them | `tests/patients.spec.ts` |
| e2e | Add: empty submit shows field errors; bad postcode refused; valid create lands on the record | `tests/patients.spec.ts` |
| e2e | The create appears in the record's Activity (real audit log) | `tests/patients.spec.ts` |
| e2e | Unknown id shows a not-available page | `tests/patients.spec.ts` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
