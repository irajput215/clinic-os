# Phase 6: patient communications and forms

**Status: IN PROGRESS.** Feature 05 (screening questionnaires and clinic-made forms) and feature 06
(the consent library) are built (2026-11-22, see "Progress"); everything else is proposed. The owner ruled that
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

## Progress

**2026-11-22: screening questionnaires (feature 05, R1–R5, R7–R9).** PHQ-9, GAD-7 and K10 are recorded
by staff on the patient record's **Questionnaires** tab, scored by their published rules, banded, and
listed over time. A PHQ-9 item 9 answer above 0 raises a safety flag in the same transaction; it shows
at the top of the tab until a clinician acknowledges it with an action. Backend
`backend/app/modules/forms/`, migration `a31b566b29ee`, tests `backend/tests/forms/`; frontend
`frontend/src/features/patients/FormsTab.tsx`.

| Decision | State |
|---|---|
| D18 which forms first | Answered by the owner: the three instruments |
| D24 schema | Approved by the owner for this slice: `form_responses`, `safety_flags` |
| D25 audit actions | Registered: `form_response.create`, `form_response.read`, `safety_flag.raise`, `safety_flag.acknowledge` (patient id only, never the instrument, score, band or rule) |
| D20 safety-flag rules | **Still open.** The proposed rule (PHQ-9 item 9 above 0) and placeholder acknowledgement actions are in code, marked PROVISIONAL. No one is notified beyond the patient record |
| D19 licensing | **Still open.** Item text is as published; marked REQUIRES LEGAL/REGULATORY VALIDATION |
| D17 manual source text | **Still open** |

**Deviation from the draft design:** instrument definitions are versioned in code
(`app/modules/forms/instruments.py`), like the consent documents, not in `form_definitions` /
`form_definition_versions` tables. The tables are only needed for clinic-authored forms (R6), which
are not built yet.

**2026-11-22: consent library (feature 06, R1–R4).** Settings → **Consents** shows each consent's
current text (the platform default, or the clinic's own) and how many patients agreed to an older
text; a practice owner publishes a new version there. On the patient record, each consent shows
Current, Re-consent needed, Withdrawn or Not given; staff record a consent given in clinic (showing the
current text first) or a withdrawal (in person, by phone or in writing). The public application offers
the clinic's current versions. Backend `backend/app/modules/consents/` (the `patient_consents` model
moved here from intake; same table), migration `74d947d74c4d`, tests `backend/tests/consents/`;
frontend `frontend/src/features/settings/ConsentsTab.tsx`, `frontend/src/features/patients/ConsentsCard.tsx`.

| Decision | State |
|---|---|
| D22 consent rules | Approved by the owner as proposed: platform defaults until a clinic publishes; a new version means re-consent, never assumed; withdrawal is append-only and effective at once |
| D24 schema | Approved for this slice: `consent_versions`, `consent_withdrawals` |
| D25 audit actions | Registered: `consent.publish` (kind and version), `consent.record` and `consent.withdraw` (patient id only) |

What a withdrawal stops is **shown** to staff on the record; nothing enforces it yet (bookings and
prescribing do not check consent). Enforcing it is a later decision. Checking consent text against the
blocked-terms list (R5) waits for the guardrail (07).

`GET /patients/{id}/consents` changed shape: it returns each kind's status and the history, not only a
list of signatures. Its one consumer, the patient record's Consents card, changed with it.

**2026-11-22: clinic-made forms (feature 05, R6).** Settings → **Forms**: a practice owner builds a
form from six field types (short text, long text, choice, 0–10 scale, date, yes/no), marks questions
required, reorders them and publishes. Editing publishes the next version; a published version never
changes, and old responses keep showing the version they were answered on. Retiring a form hides it
and stops new responses; its responses stay. On the patient's Questionnaires tab the clinic's forms sit
beside PHQ-9, GAD-7 and K10; answers are checked per field on the server (a refusal names the field)
and shown in a "Clinic forms" history. Backend: `clinic_forms`, `clinic_form_versions`,
`clinic_form_responses` (migration `f06c7a29ab0c`; versions and responses append-only, answers
encrypted), routes in `backend/app/modules/forms/router.py`, tests
`backend/tests/forms/test_clinic_forms.py`. Frontend `frontend/src/features/settings/FormsTab.tsx`.

**Two deviations from the draft design, both recorded here:** clinic forms have their **own**
response table rather than sharing `form_responses`, so that table keeps guaranteeing every row is a
scored, banded instrument; and clinic forms are **not scored and raise no safety flags** (a flag rule
is a Clinical Safety Officer decision, D20, not something a form author declares). Checking form text
against the blocked-terms list waits for the guardrail (07).

Not built yet: remote completion (05b, needs D21), the guardrail (07, needs D23), SMS (08, needs D7a).
