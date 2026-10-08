# TGA approvals: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| Switch to `api` after `feat/tga-approvals-engine` merges | done for the patient tab, Overview card and all writes: `tgaApprovals: "api"`, preview code removed, `tests/approvals.spec.ts` |
| Tenant-wide register endpoint | done (M2 phase 2A): `GET /api/v1/tga-approvals` ([api.md](api.md), agreed 2026-10-07) with state and expiry filters, keyset paging, practice totals and `tga_approval.read` audit (`backend/tests/tga/test_register.py`); the register reads it with filters and Show more, refusal removed (`tests/approvals.spec.ts`) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
