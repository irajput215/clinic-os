# Patient record: Definition of Done

| Item | Status |
|---|---|
| Owner approved the schema changes (`patients` columns, `patient_alerts`, `patient_emergency_contacts`) | open |
| Security Lead approved interim key custody and rotation (D13); Privacy Officer the Medicare format rule (D12) | open |
| Migration with backfill; check constraints named per convention; `alembic check` clean; schema diagram regenerated | open |
| Medicare and IHI encrypted at rest, blind-indexed, masked on every response; never in logs, errors, audit or URLs | open |
| `BLOCKED` enforced on staff booking, public application and staging (fail closed) | open |
| Every status, alert and contact change audited in the same transaction | open |
| Header, dialogs, list filter: every state designed; keyboard and screen-reader reachable | open |
| `ruff`, `mypy`, `pytest`, lint, typecheck, Playwright green | open |
| `docs/features/05-patients` R8/R9 marked built; `docs2/sdlc/02-patients` updated | open |

Platform DoD: [`docs/reference/definition-of-done.md`](../../docs/reference/definition-of-done.md).
