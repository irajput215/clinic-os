# TGA approvals: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Switch to `api` after `feat/tga-approvals-engine` merges | done for the patient tab, Overview card and all writes: `tgaApprovals: "api"`, preview code removed, `tests/approvals.spec.ts` |
| Tenant-wide register endpoint | open: backend. Until `GET /tga-approvals` lands the register shows a designed refusal naming it (no preview data), tested in `tests/approvals.spec.ts` |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
