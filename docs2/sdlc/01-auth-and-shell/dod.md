# Auth and app shell: Definition of Done

| Item | Status |
|---|---|
| Typecheck (`bun run typecheck`) and lint (`bun run lint:ci`) clean | done |
| Every state designed: loading, empty, error, `403`, refusal | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| No PHI in URLs; no `dangerouslySetInnerHTML` | done |
| End-to-end tests in `tests/` pass against a real backend | done |
| `GET /users/me/permissions` agreed with the backend owner | done |
| Signup, password recovery and reset rebuilt from the removed `frontend/` (R10 to R13), e2e in `tests/account.spec.ts` | done |
| Administration rebuilt from the removed `frontend/` (R14, R15), e2e in `tests/admin.spec.ts` | done |
| Settings rebuilt from the removed `frontend/` (R16), e2e in `tests/settings.spec.ts` | done |
| Served by the backend at `/` from the production build; CI e2e runs against that build ([ADR-F005](../../adr/ADR-F005-one-app-served-by-the-backend.md)) | done |

`GET /api/v1/users/me/permissions` is served by `backend/app/modules/users_roles/router.py`
(`read_own_permissions`) and tested in `backend/tests/users/test_own_permissions.py`. It is the
design's self-permissions row (named `GET /api/v1/auth/capabilities` until the owner settled the path
on 2026-10-07)
([`docs/features/03-users-and-roles/03-design.md`](../../../docs/features/03-users-and-roles/03-design.md),
"Endpoints": valid session, advisory UI data only, never a control). It writes no audit event: the
closed action catalogue in
[`docs/features/04-audit-log/05-data-and-audit.md`](../../../docs/features/04-audit-log/05-data-and-audit.md)
names none for a permission read.

Platform DoD: [`docs/reference/definition-of-done.md`](../../../docs/reference/definition-of-done.md).
