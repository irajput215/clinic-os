# SDLC: one folder per feature

Each feature folder holds the same five documents:

| File | Holds |
|---|---|
| `requirements.md` | Who it's for, user stories, functional requirements (R-n), non-functional requirements, out of scope |
| `design.md` | Screens, components, states (loading / empty / error / `403` / refusal), data flow |
| `api.md` | Endpoints the screens call: **existing** (with source file) or **proposed** (the contract for the backend owner) |
| `test-plan.md` | What is tested, where, and the cases that must exist |
| `dod.md` | Definition of Done for this feature, with the current status of each item |

The platform requirements and invariants in [`docs/features/`](../../docs/features/) still apply.
These documents cover the UI and the UI-facing contracts.

| # | Feature |
|---|---|
| 01 | [Auth and app shell](01-auth-and-shell/) |
| 02 | [Patients](02-patients/) |
| 03 | [Consult notes](03-consult-notes/) |
| 04 | [Calendar and booking](04-calendar-and-booking/) |
| 05 | [TGA approvals](05-approvals/) |
| 06 | [Patient activity](06-patient-activity/) |
| 07 | [Script queue and safety gate](07-script-queue/) |
| 08 | [Today](08-today/) |
