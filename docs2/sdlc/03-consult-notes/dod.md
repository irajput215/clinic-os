# Consult notes: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Switch to `api` after `feat/clinical-records` merges; e2e added | done: reads the API, preview code removed, `tests/consult-notes.spec.ts` (the per-feature switch itself was retired with the preview store, [ADR-F006](../../adr/ADR-F006-preview-store-retired.md)) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
