# Clinic setup: Definition of Done

| Item | Status |
|---|---|
| Owner approved the `tenant_settings` schema change | done (owner: build without asking) |
| `tenant_settings` migration with forced RLS; `alembic check` reports no operations; schema diagram regenerated | done |
| `GET /tenants/current/setup`, `GET/PATCH /tenants/current/settings` with denial tests first | done |
| Setup read is one round trip, pinned in `test_round_trips.py` | open (two statements: the facts, then the prescribers' packs; not pinned yet) |
| Settings changes audited in the same transaction | done |
| Checklist card and Settings → Practice tab: every state designed (loading, empty, error, `403`) | done |
| Keyboard and screen-reader reachable; labels on every control | done |
| `ruff`, `mypy`, `pytest`, `bun run lint`, `bun run typecheck`, Playwright green | done |
| `docs2/sdlc/` updated with the as-built screens | open |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
