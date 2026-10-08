# Patients: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Server-side search and keyset paging: every patient reachable (`POST /patients/search`, `GET /patients?cursor=`) | done |
| Every patient picker in the app searches the server: calendar booking, staging a script and recording a TGA approval (the last read only the first 25 patients until M2 phase 2F; `features/shared/PatientPicker.tsx`) | done |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
