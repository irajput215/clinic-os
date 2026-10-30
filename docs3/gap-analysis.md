# Gap analysis: Platform Manual v2.5 vs the code

Checked against `main` at `7915eb4` (2026-10-30). ✅ built · 🟡 partial · ❌ missing · ⏸ blocked on a
decision. **Onboarding** marks what Phase 5 depends on.

## By chapter

| Ch. | Manual | State | Evidence in the code | Onboarding |
|---|---|---|---|:---:|
| 1.1 | Personal sign-in, sign out, no shared logins | ✅ | `/login`, `POST /login/access-token`; 15-min tokens | |
| 1.1 | "No self-serve password reset" | 🟡 conflict | Code *has* self-serve recovery (`/recover-password`) — D1 | |
| 1.2 | Sidebar: Care · Prescribing · Business · Practice; live badges; doctors see a slimmed menu | 🟡 | Today, Calendar, Patients, Approvals, Script queue, Admin, Settings exist. No Waitlist, Catalogue, Pharmacy network, Billing, Automations, Forms, Reports, Inbox, SOPs | |
| 1.3 | Global search `/`: patients, actions, pages | 🟡 | Patient quick-find in the top bar (`POST /patients/search`); no actions or pages | |
| 1.4 | Permission grid; identity-bound prescribing; External Partner hard wall | 🟡 | 7 roles × 22 permissions, `RolesMatrix.tsx`; `PHARMACY` role holds `patient:read`, so the manual's External Partner hard wall is **not** modelled. Grid toggling is not step-up protected; roles are fixed (OPEN-2) | ✓ |
| 2 | Today: 4 KPI cards, Needs attention | 🟡 | `GET /dashboard/today` (appointments, scripts, approvals). No payments card, no feed | ✓ |
| 3.1 | Patient list, status filter, xlsx import | 🟡 | List + server search + keyset paging. No status filter, no import | ✓ |
| 3.2 | 8 lifecycle statuses | ❌ | Only `deceased_at`, `merged_into_patient_id`, `deleted_at` | ✓ |
| 3.3 | Profile: 8 tabs | 🟡 | Overview, Consult notes, Appointments, Approvals, Scripts, Activity. No Invoices, Forms & consent, Comms | |
| 3.4 | Fields: sex, address, timezone, Medicare verify + IHI, alerts, emergency contacts, comms flag | 🟡 | Name, DOB, sex, gender, address, phone, email ✅. Medicare/IHI columns + blind-index columns exist but unused. No alerts, emergency contacts, comms flag, timezone | ✓ |
| 3.4 | eScript-ready chip (IHI + street address) | ❌ | — | ✓ |
| 3.5 | Change pharmacy | ❌ | No pharmacy directory | ✓ |
| 4 | Calendar views, bookings, status machine | 🟡 | Day/week, booking, status machine, clinic hours (R8). No month/year, rosters, leave, delay tool, capacity | |
| 5.1 | Six-step public application | 🟡 | `/book/<slug>`: short questionnaire (18+, help wanted, what tried), name/DOB/mobile/email, APP 5 consent, slot. No sex/address, health screen, cannabis history, versioned consents, pharmacy, declaration | ✓ |
| 5.2 | Book with card payment | 🟡 | Slot booking ✅; payment ❌ (vendor — D7) | |
| 5.3 | Returning patients: DOB + mobile + SMS code portal | ❌ ⏸ | Needs an SMS vendor (D7) | |
| 5.4 | Online applications queue; accept / reject; briefing note | ❌ | Public bookings land on the calendar marked "from the booking page"; `match_or_create_for_booking` creates or matches the patient | ✓ |
| 6 | Drug catalogue, staging, review & sign, Parchment | 🟡 | Prescriptions, safety gate, staging, sign with step-up, cancel, addendum, dispatch to `QUEUED`. No catalogue screen, no RTPM, no Parchment ⏸ | |
| 7 | Approvals register, record, TGA inbox, AP report | 🟡 | Register, record, verify, supersede, revoke ✅. TGA inbox ❌ (`tga_inbox:process` exists, no route). AP report ❌ | |
| 8 | Pharmacy network, stock, dispatch bundle | ❌ ⏸ | Dispatch queues only; no transport (open-questions §1.5) | ✓ (directory) |
| 9 | Invoices, pay runs, Medicare bulk billing | ❌ ⏸ | — (Tyro is a vendor decision) | |
| 10 | Reports, AP six-monthly | ❌ | `reports:export` permission only | |
| 11 | Automations, campaigns, comms guardrail | 🟡 | Booking confirmation + reminder emails (outbox, D-009). No recipes, campaigns, guardrail | |
| 12 | Forms & instruments, consent versioning | ❌ | APP 5 consent checkbox on booking only | ✓ (consents) |
| 13 | SOPs, versioning, per-person acknowledgement | ❌ | — | ✓ |
| 14 | Inbox, Patient mail | ❌ | — | |
| 15.1 | Permission grid with step-up toggles | 🟡 | Grid ✅; step-up exists for scripts (`/auth/step-up`) but not for the grid | ✓ |
| 15.2 | Users & sessions, doctor onboarding pack, credential vault | 🟡 | Staff list, invitations (expiring, single-use, resend), role grants ✅. No pack, no vault | ✓ |
| 15.3 | Integrations: Parchment, Tyro, Google Places | ❌ ⏸ | — | ✓ (status only) |
| 15.4 | Audit & compliance pack | 🟡 | Hash-chained audit log, `GET /audit/events`, archive. No one-click pack | |
| 15.5 | Switch Kit; clinic settings (workflow model, retention, rates) | 🟡 | Display name, hours, slot length ✅. No workflow model, retention setting, rates, Switch Kit | ✓ |
| 16 | Clinical mode (Bp skin) | ❌ | — | |
| A | Parchment eScripts | ⏸ | `transport.py`: `configured_transport()` returns `None` | |
| B | Categories, dosage forms | ✅ | `tga_approvals` grain constraint | |
| C | Step-up, immutable audit, AU residency, no hard deletes | 🟡 | ✅ except: app runs in `us-east-1` while the DB is in Sydney (`docs/reference/performance.md` §5), and production may connect as `neondb_owner` (RLS bypassed, `docs/progress.md` P5) | |

## What onboarding already has

- **Clinic:** organisation signup with email verification (D-008) creates the tenant and the Practice
  Owner; display name; hours and slot length; roles screen.
- **Staff:** `POST /users/invitations` → emailed link → `/accept-invite` sets a password; resend; derived
  `INVITED` status (`staff_invitations`).
- **Patients:** `/book/<slug>` with an eligibility questionnaire and slot picker; exact-match-or-create
  of the patient (`patients.match_or_create_for_booking`).

## What blocks a clinic going live on onboarding alone

1. No **guided first run** — a verified owner lands on an empty Today with nothing telling them what next.
2. No **application review** — every public booking becomes a patient immediately, unreviewed.
3. No **consent record** beyond one checkbox; nothing version-locked.
4. No **prescriber readiness** — nothing records AHPRA, HPI-I or prescriber numbers, so nothing stops an
   unregistered account from signing.
5. The patient record can't hold what an eScript needs (verified IHI, structured address, alerts).
