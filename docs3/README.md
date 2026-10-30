# docs3: Phase 5 — functional onboarding

`docs3/` plans the next phase of ClinicOS: taking a new clinic, its staff and its patients from
"nothing" to "working" without anyone from the build team in the room. It is written against the
**Clinic OS Platform Manual v2.5 (Aug 2026)** — the reference product at
`clinic-os-banksia.vercel.app` — and against the code on `main` as of 2026-10-30.

**Status: PROPOSED.** Nothing here is built. Every new table, vendor and rule below needs the owner's
approval first ([AGENTS.md](../AGENTS.md) "Ask first"); [decisions-needed.md](decisions-needed.md)
lists each one.

## How docs3 relates to docs/ and docs2/

| Set | Owns | When they disagree |
|---|---|---|
| [`docs/`](../docs/README.md) | Requirements, invariants, gates, the backend contract | `docs/` wins |
| [`docs2/`](../docs2/README.md) | The web app as built: screens, API each screen reads | `docs/` wins |
| `docs3/` | What Phase 5 adds, mapped to the manual and to the code | `docs/` wins; a conflict is recorded in [decisions-needed.md](decisions-needed.md), never silently resolved |

## Scope

Onboarding has three audiences. Phase 5 covers all three, in this order:

| # | Feature | For | Manual |
|---|---|---|---|
| 01 | [Clinic setup](01-clinic-setup/) | Practice Owner / Manager: a guided first-run checklist and the practice settings | Quick-start "Practice manager", §15.5 |
| 02 | [Staff onboarding](02-staff-onboarding/) | Every new staff member; the doctor onboarding pack and credential vault for prescribers | Quick-starts, §1.1, §13, §15.2 |
| 03 | [Patient intake](03-patient-intake/) | New patients: the six-step public application → the clinic's applications queue → a patient record | §5 |
| 04 | [Patient record](04-patient-record/) | Reception: the fields onboarding fills — statuses, alerts, emergency contacts, comms flag, Medicare/IHI, eScript-ready | §3.2, §3.4 |

**03 is the centrepiece.** 04 is what 03 writes into; 01 and 02 make sure a clinic and its people are
ready before the first application arrives.

Out of scope (see [roadmap.md](roadmap.md)): payments, SMS, the patient portal, pharmacy dispatch,
billing and Medicare claiming, forms library, inbox, reports, Clinical mode.

## Each feature folder

The same five files as `docs2/sdlc/`:

| File | Answers |
|---|---|
| `requirements.md` | User stories and numbered requirements, each citing the manual section |
| `design.md` | Screens, states, data model and data flow |
| `api.md` | Endpoints added or changed, permissions, errors |
| `test-plan.md` | The tests that prove it, denial paths first |
| `dod.md` | What "done" means for this feature |

## Also here

- [gap-analysis.md](gap-analysis.md) — every manual chapter against the code: built, partial, missing.
- [decisions-needed.md](decisions-needed.md) — conflicts, vendors and schema changes waiting on the owner.
- [roadmap.md](roadmap.md) — the phases after onboarding.

## Assumption recorded

The intake keeps the manual's **medicinal-cannabis** specifics (cannabis-history step, TGA category ×
dosage form). The code's TGA approval engine already uses categories 1–5. If ClinicOS is to serve other
therapeutic areas, step 3 becomes a general "prior treatment" step — [decisions-needed.md](decisions-needed.md) D5.
