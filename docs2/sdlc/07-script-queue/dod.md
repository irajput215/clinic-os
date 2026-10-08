# Script queue and safety gate: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Prescriptions backend built to the contract; switch `prescriptions` to `api` | done (Milestone 2, phase 2D: `backend/app/modules/prescriptions/`, `tests/prescriptions/`; gate inside the sign and dispatch transactions with the approval rows locked `FOR UPDATE`; revoke-vs-sign race tested both ways) |
| Server-side step-up for sign and dispatch | done, interim (ADR-F002 password re-entry checked by `POST /api/v1/auth/step-up`; single use, 2 minutes, bound to user + operation + script) |
| Real step-up factor (MFA) | open: D-003 |
| Real pharmacy / eRx transport | open: no transport exists; dispatch is honestly `QUEUED`, see [api.md](api.md) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
