# Today: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done (a withheld section shows the role boundary) |
| Keyboard and screen-reader reachable; labels on every control | done (cards are named regions; schedule rows are focusable) |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done (`tests/today.spec.ts`) |
| Dashboard endpoint; switch `dashboard` to `api` | done (Milestone 2, phase 2E: `backend/app/modules/dashboard/`, `tests/dashboard/`; the page reads `GET /api/v1/dashboard/today`; the preview store is deleted, [ADR-F006](../../adr/ADR-F006-preview-store-retired.md)) |
| Whole-page read audit | open: needs a catalogue action, the owner's decision ([api.md](api.md#audited)) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
