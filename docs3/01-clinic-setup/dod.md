# Clinic setup: Definition of Done

| Item | Status |
|---|---|
| Owner approved the `tenant_settings` schema change | open |
| `tenant_settings` migration with forced RLS; `alembic check` reports no operations; schema diagram regenerated | open |
| `GET /tenants/current/setup`, `GET/PATCH /tenants/current/settings` with denial tests first | open |
| Setup read is one round trip, pinned in `test_round_trips.py` | open |
| Settings changes audited in the same transaction | open |
| Checklist card and Settings → Practice tab: every state designed (loading, empty, error, `403`) | open |
| Keyboard and screen-reader reachable; labels on every control | open |
| `ruff`, `mypy`, `pytest`, `bun run lint`, `bun run typecheck`, Playwright green | open |
| `docs2/sdlc/` updated with the as-built screens | open |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
