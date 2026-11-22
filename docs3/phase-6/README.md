# Phase 6: patient communications and forms

**Status: PROPOSED (2026-11-22).** Nothing here is built. The owner ruled that
[`docs3/roadmap.md`](../roadmap.md) governs the order of work (reconciliation C1, 2026-11-21); this
folder plans its Phase 6. Every new table, vendor and clinical rule waits for the decisions listed in
[`../decisions-needed.md`](../decisions-needed.md) §"Phase 6" (D17–D25).

**Source gap.** The roadmap cites the Clinic OS Platform Manual v2.5 §11 (communications) and §12
(forms and instruments). The manual is not in this repository, so the requirements below are written
from the roadmap's summary, the code and general clinical practice, and each one that should come
from the manual is marked **(manual §n: confirm)**. D17 asks for those sections.

## What exists today

| Area | In the code | Where |
|---|---|---|
| Consent | Three platform consent documents (privacy, telehealth, treatment) as versioned constants; a patient's agreement is an append-only `patient_consents` row with the version and the SHA-256 of the exact text | `backend/app/modules/intake/consents.py`, `models.py` |
| Patient email | Booking confirmations and reminders through the approved SMTP flow (D-009) | `backend/app/modules/appointments/notifications.py` |
| Patient alerts | Header chips with a tone, on the patient record | `patient_alerts` (docs3 04) |
| Forms, instruments, SMS, bulk messages | None | — |

## Scope and proposed order

| # | Feature | Depends on | Can start when |
|---|---|---|---|
| 05 | [Forms and instruments](05-forms-and-instruments/): PHQ-9, GAD-7, K10 and clinic forms, scored, with live safety flags | D18, D19, D20; schema approval | Decisions answered. **No vendor needed**: staff enter answers in clinic first |
| 06 | [Consent library](06-consent-library/): clinic-published, versioned consents, re-consent and withdrawal | D22; schema approval | Decisions answered |
| 05b | Remote completion: a patient fills a form from an emailed single-use link | D21 | After 05; uses the existing email flow |
| 07 | [Comms guardrail](07-comms-guardrail/): blocked terms in patient-facing messages | D23 | Decision answered; bulk sends do not exist yet, so it guards templates first |
| 08 | [SMS](08-sms/): reminders, "with the doctor", portal OTP | **D7a** (vendor) | A vendor is approved |

05 is the centrepiece: it is the part with the most clinical value and no external dependency.

## What is deliberately not in Phase 6

- A patient portal with log-in (needs SMS OTP, D7a).
- Diagnosis or treatment suggestions from a score. A score and a flag inform a clinician; they never
  decide (the briefing-note rule, D11).
- Bulk campaigns. The guardrail is planned so that campaigns, when they come (Phase 9 automations),
  cannot bypass it.
