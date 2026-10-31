# Staff onboarding: Definition of Done

| Item | Status |
|---|---|
| Owner approved the schema changes (`practitioner_identifiers`, `practitioner_agreements`, `sops`, `sop_versions`, `sop_acknowledgements`) | done (owner: build without asking) |
| Clinical Safety Officer approved the signing gate (D8) | open |
| Security Lead approved attestation as interim verification (D9) and the key custody (D13) | open |
| Migrations with forced RLS and append-only grants; `alembic check` clean; schema diagram regenerated | done |
| Every route with denial tests first; step-up on identifier changes; `404` across tenants | done |
| Sign gate in the signing transaction, fail closed, audited on refusal | done |
| No identifier value in logs, audit payloads, errors or URLs (INV-5) | done (test asserts responses, audit and storage) |
| New audit actions registered in `audit/actions.py` before use | done |
| Staff column, pack dialog, first-hour card, SOP pages: every state designed; keyboard and screen-reader reachable | done |
| `ruff`, `mypy`, `pytest`, lint, typecheck, Playwright green | done |
| `docs/features/03-users-and-roles` and `docs2/sdlc/01-auth-and-shell` updated as built | open |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
