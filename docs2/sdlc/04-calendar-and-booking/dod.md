# Calendar and booking: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Backend module built to the contract above; switch `appointments` and `publicBooking` to `api` | done (`backend/app/modules/appointments/`, contract agreed 2026-10-07; preview implementation deleted) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
