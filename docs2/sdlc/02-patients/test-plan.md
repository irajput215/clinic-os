# Patients: test plan

| Level | Case | Where |
|---|---|---|
| e2e | The list shows API patients; the server search narrows them by name and by date of birth, and the term is in no URL | `tests/patients.spec.ts` |
| e2e | Past 25 patients, Load more reaches the rest, and the quick-find opens a patient beyond the first page | `tests/patients.spec.ts` |
| api | Search and paging denials, isolation, wildcard escaping, cursor binding, audit and rate limit | `backend/tests/patients/test_search.py` |
| e2e | Add: empty submit shows field errors; bad postcode refused; valid create lands on the record | `tests/patients.spec.ts` |
| e2e | The create appears in the record's Activity (real audit log) | `tests/patients.spec.ts` |
| e2e | Unknown id shows a not-available page | `tests/patients.spec.ts` |
| api | T1-34: deny paths (no, ended, colleague's or other-tenant relationship; update; care-team refusals), audit fields, `404` across tenants, successes | `backend/tests/api/test_patients_relationship.py` |
| e2e | T1-34: a doctor off the care team is refused politely; added to it, the record opens; ended, refused again | `tests/care-team.spec.ts` |

E2E runs against a real backend: `bun run test` (see [README](../../README.md)).
