# Patient intake: Definition of Done

| Item | Status |
|---|---|
| Owner decided D5 (cannabis-specific) and D6 (patient created at submission) | done (owner: build without asking) |
| Owner approved the schema changes (`intake_applications`, `patient_consents`, `pharmacies`, `patients.preferred_pharmacy_id`) | done |
| Privacy Officer reviewed the collected fields and their classification (`answers` is HIGHLY_SENSITIVE) | open |
| Migrations with forced RLS, append-only grants on consent tables; `alembic check` clean; schema diagram regenerated | done |
| Public submit is one transaction, no enumeration, body never logged | done |
| Accept / reject audited in the same transaction; no double decision | done |
| No product or brand name on any public surface (test enforced) | open |
| Six-step form, queue, briefing, consents: every state designed; works at 360 px; keyboard and screen-reader reachable | done |
| `ruff`, `mypy`, `pytest`, lint, typecheck, Playwright green | done |
| `docs2/sdlc/04-calendar-and-booking` and `docs/features/05-patients` updated as built | open |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
