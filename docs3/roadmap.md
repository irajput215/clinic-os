# Roadmap after onboarding

Ordered by what a live clinic needs next. Each phase starts with its own decisions from
[decisions-needed.md](decisions-needed.md).

## Before any of it: go-live blockers (not features)

| Item | Why | Where |
|---|---|---|
| Run the app as `clinos_app`, not `neondb_owner` | RLS is bypassed otherwise (INV-1) | `docs/progress.md` P5 |
| Move the app next to the database (Sydney) | ~210 ms per DB round trip from `us-east-1`; health data leaves AU | `docs/reference/performance.md` §5 |
| Neon scale-to-zero off | 2.6–3.9 s first request after idle | same |

## Phase 5 — functional onboarding (this folder)

01 Clinic setup · 02 Staff onboarding · 03 Patient intake · 04 Patient record.

## Phase 6 — patient communications and forms

- SMS vendor (D7a) → "with the doctor" SMS, reminders by SMS, OTP patient portal (manual §5.3).
- Forms & consent library: intake, follow-up, PHQ-9/GAD-7/K10 instruments with live safety flags (§12).
- Comms guardrail: banned product/brand terms blocked on bulk sends (§11).

## Phase 7 — pharmacy and eScripts

- Drug catalogue screen (§6.1), pharmacy network with stock signals (§8.1).
- Pharmacy bundle email (§8.2) and manual-handoff items (§8.4).
- Parchment eRx rail (App. A) once D7e and the conformant-party contract are settled.
- TGA inbox: approvals that file themselves (§7.3).

## Phase 8 — billing and Medicare

- Invoices and fees (§9.1); card payment at booking (D7b).
- Medicare bulk billing with Tyro (§9.4), MyMedicare drive.
- Doctor pay runs and `.aba` export (§9.3).

## Phase 9 — practice operations

- Inbox and Patient mail (§14); Needs-attention feed on Today (§2.2).
- Reports and the AP six-monthly report (§10).
- Rosters, leave, delay tool, capacity (§4.3–4.4); Waitlist.
- Audit & compliance pack, one click (§15.4); Switch Kit and xlsx import (§3.5, §15.5).

## Phase 10 — Clinical mode

The Bp-style skin (§16): appointment book, Open patient, clinical patient window, Represcribe, Finalise
visit. A presentation layer over the same API; no new data.
