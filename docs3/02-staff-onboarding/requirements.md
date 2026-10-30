# Staff onboarding: requirements

**For:** every new staff member, and the Practice Owner who brings them on.
**Manual:** "Day-one quick-starts by role"; §1.1; §13; §15.1; §15.2; App. C.

## User stories

- As a Practice Owner, I invite a staff member with a role, and see where their onboarding stands.
- As a newly invited nurse, doctor or receptionist, my first sign-in shows me "your first hour" for my role.
- As a Practice Owner, I record a doctor's AHPRA, HPI-I, prescriber and Medicare provider numbers, the
  agreement they signed, and see a pack that stamps complete when everything is in.
- As a doctor, I cannot sign a script until my pack is complete — and I am told exactly what is missing.
- As any staff member, I acknowledge the current version of each SOP that applies to my role; a new
  version asks me again.

## Requirements

### Invitation and first sign-in (builds on what exists)

| # | Requirement | Manual |
|---|---|---|
| R1 | Inviting stays as built: `POST /users/invitations`, an expiring single-use link, resend, derived `INVITED` status (`docs/features/03-users-and-roles`) | §15.2 |
| R2 | The staff list shows an **onboarding column** per person: Invited · Active · Pack incomplete (prescribers) · Ready | §15.2 |
| R3 | On a person's first sign-in after accepting, Today shows a **"Your first hour"** card for their role, built from the manual's quick-starts (Reception/Admin, Nurse, Doctor, Practice Manager). Each line links to the screen it names; lines for screens not yet built are omitted, never shown broken. Dismissible per person | Quick-starts |
| R4 | A person holding several roles sees the card for each | |

### SOPs and acknowledgement (minimal slice of §13)

| # | Requirement | Manual |
|---|---|---|
| R5 | A holder of `tenant:configure` publishes an **SOP**: title, plain-text body (headings, lists, emphasis), the roles it applies to, and whether it is **required for onboarding** | §13 |
| R6 | Publishing creates version 1; editing publishes v2, v3… History is kept; no version is ever changed or deleted | §13 |
| R7 | A staff member acknowledges the **current** version of each SOP that applies to their roles. A new version resets acknowledgement for everyone it applies to and shows a badge | §13 |
| R8 | The **acknowledgement matrix** (staff × SOP × version) is visible to `tenant:configure` and `audit:read` | §13 |
| R9 | Printing stamps **UNCONTROLLED COPY** | §13 |

### Doctor onboarding pack and credential vault

| # | Requirement | Manual |
|---|---|---|
| R10 | Granting `DOCTOR` or `AUTHORISED_PRESCRIBER` creates **pending** vault entries for that person: AHPRA registration, HPI-I, prescriber number, Medicare provider number (per location). The eRx connection ID appears as "Not available — eScripts not connected" until decision D7e | §15.2 |
| R11 | A `tenant:configure` holder records each identifier's value and marks it **active** by attestation: who checked, when, and how (e.g. "AHPRA public register"). Status: pending → active → expiring (≤ 60 days to expiry, where an expiry applies) → expired. Each change needs **step-up** and is audited | §15.2, App. C; D9 |
| R12 | Identifier formats are validated on entry (confirm against each issuer, D16): AHPRA `MED` + 10 digits; HPI-I 16 digits starting `800361`; prescriber number 7 digits; provider number 6 digits + location character + check character | §15.2 |
| R13 | The **agreement**: a `tenant:configure` holder records that the doctor signed agreement version *X* on date *Y*, attested by *Z* (the document itself waits for Feature 07 — D10) | §15.2 |
| R14 | The pack shows three ticks: ① agreement recorded ② AHPRA + prescriber number active ③ every SOP **required for onboarding** that applies to the doctor acknowledged at its current version. All three → **Pack complete** | §15.2 |
| R15 | **Signing gate (fail closed, D8):** `POST /prescriptions/{id}/sign` is refused while the signer's pack is incomplete, with `403 PRESCRIBER_NOT_READY` naming each missing item. The check runs in the signing transaction; a missing pack reads as incomplete | §15.2 |
| R16 | Identifier values are visible only to the person themself and to `tenant:configure` / `audit:read`; every read of the vault is audited. They never appear in logs or errors (INV-5) | App. C |
| R17 | An identifier becoming *expiring* or *expired* raises a dashboard item for the owner and the doctor (reuses the Today approvals-expiry pattern) | §2.2 |

## Out of scope

Live AHPRA / HI Service verification (D7d, D9); agreement PDF storage (D10); custom roles (OPEN-2);
leave requests and rosters (Phase 9); session list and remote sign-out (Feature 02, blocked on D-003).
