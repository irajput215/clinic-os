# Patient record: Definition of Done

| Item | Status |
|---|---|
| Owner approved the schema changes (`patients` columns, `patient_alerts`, `patient_emergency_contacts`) | done (owner: build without asking, 2026-10-30) |
| Security Lead approved interim key custody and rotation (D13); Privacy Officer the Medicare format rule (D12) | interim built: `FIELD_ENCRYPTION_KEY`, else derived from `SECRET_KEY`; format check only. Ratification open |
| Migration with backfill; check constraints named per convention; `alembic check` clean; schema diagram regenerated | done |
| Medicare and IHI encrypted at rest, blind-indexed, masked on every response; never in logs, errors, audit or URLs | done |
| `BLOCKED` enforced on staff booking, public application and staging (fail closed) | done |
| Every status, alert and contact change audited in the same transaction | done |
| Header, dialogs, list filter: every state designed; keyboard and screen-reader reachable | done |
| `ruff`, `mypy`, `pytest`, lint, typecheck, Playwright green | done |
| `docs/features/05-patients` R8/R9 marked built; `docs2/sdlc/02-patients` updated | done (docs2 api) |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
