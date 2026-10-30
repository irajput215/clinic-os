# Decisions needed before Phase 5 is built

Each row is open. The column "Proposed" is a recommendation, not a decision. Nothing that depends on a
row is built until the owner (or the named role) answers it.

## Conflicts between the manual and the contract

| # | Topic | Manual says | Code / contract says | Proposed | Owner |
|---|---|---|---|---|---|
| D1 | Password reset | No self-serve reset; the PM resets (§1.1) | Self-serve recovery with a rate limit (`docs/features/02-authentication`) | **Keep self-serve.** A multi-clinic product cannot route every reset through a PM | Security Lead |
| D2 | Session storage | Secure cookies per device (App. C) | Bearer token in `sessionStorage` ([ADR-F002](../docs2/adr/ADR-F002-token-storage.md)) | **Keep ADR-F002** until D-003 (identity model) closes | CTO + Security Lead |
| D3 | One clinic vs many | One clinic ("Banksia Family Medical") | Multi-tenant SaaS; a tenant is an organisation, `clinics` are its sites | **Keep multi-tenant.** Manual "clinic" = our tenant | CTO |
| D4 | Offline sync (App. C) | Changes queue offline, converge across devices | Server is the only source of truth (INV-3) | **Do not build offline writes.** Show a connection badge only | CTO |
| D5 | Cannabis-specific intake | Step 3 "Cannabis history" | TGA categories 1–5 already in the approvals engine | **Keep cannabis-specific** (assumed in these docs) | Practice Owner |

## Onboarding design choices

| # | Topic | Proposed | Owner |
|---|---|---|---|
| D6 | When does an applicant become a patient? | **At submission, as today** (`match_or_create_for_booking`), with an `intake_applications` row in `SUBMITTED`. *Accept* files consents and the declaration and makes the patient `CURRENT`; *Reject* cancels the held appointment and sets the patient `ARCHIVED` with the reason. Avoids making `appointments.patient_id` nullable | CTO |
| D8 | Doctor readiness gate | A prescriber cannot **sign** while their pack is incomplete: AHPRA + prescriber number `ACTIVE`, agreement recorded, required SOPs acknowledged. Fails closed. Changes `prescriptions` sign rules | Clinical Safety Officer |
| D9 | Identifier verification | Interim: **attested by a Practice Owner** (who, when, how checked), audited. No AHPRA / HI Service lookup until a vendor is approved | Security Lead |
| D10 | Doctor's agreement document | Interim: record *signed on / version / attested by* only. Storing the PDF waits for Feature 07 (documents, S3) | Practice Owner |
| D11 | Briefing-note "range suggestion" | **Not in Phase 5.** It needs a drug catalogue and a Clinical Safety Officer ruling; the note shows the patient's own answers only | Clinical Safety Officer |
| D12 | Medicare check | Format check only (10 digits, IRN 1–9). The check-digit algorithm is unconfirmed (`open-questions.md` O2) | Head of Product + Privacy Officer |
| D13 | Identifier encryption keys | Interim: one AES-GCM key and one HMAC key from app settings, versioned for rotation (`open-questions.md` O5) | Security Lead |
| D14 | Permission-grid step-up | Require step-up for role grants and revocations (manual §15.1) | Security Lead |
| D15 | External Partner hard wall | The manual's External Partner has **no path** to patient data; the code's `PHARMACY` role holds `patient:read`. Proposed: remove `patient:read` from `PHARMACY` once dispatch (Phase 7) gives pharmacies only what a script carries | CTO + Security Lead |
| D16 | Practitioner identifier formats | AHPRA `XXX` + 10 digits, HPI-I `800361…` (16), prescriber number 7 digits, provider number 6 + 2 characters — confirm against each issuer before build, as D12 | Head of Product |

## New third-party data flows (AGENTS.md: ask first)

None of these is in Phase 5. The docs show each as "not connected" until approved.

| # | Vendor need | Manual | Data that would leave ClinicOS |
|---|---|---|---|
| D7a | SMS provider | OTP portal, reminders, "with the doctor" SMS | Mobile number, message text |
| D7b | Card payments | Pay at booking | Name, amount, card (tokenised) |
| D7c | Google Places | Address autocomplete | Typed address fragments |
| D7d | Medicare OPV / HI Service | Verify Medicare, fetch IHI | Name, DOB, sex, Medicare |
| D7e | Parchment (eRx) | Signing, tokens | Full script + patient identity |
| D7f | CAPTCHA | (Not in manual) public application abuse | Browser fingerprint |

## Schema changes (AGENTS.md: ask first)

All tenant-scoped with forced RLS, `tenant_id` resolved never supplied, no `DELETE` grant to `clinos_app`.

| Table / column | Feature | Why |
|---|---|---|
| `patients.status`, `patients.status_reason` | 04 | 8 lifecycle statuses |
| `patients.receives_communications`, `patients.timezone`, `patients.preferred_pharmacy_id`, `patients.medicare_irn` | 04 | Comms opt-out, reminders, pharmacy, Medicare IRN |
| `patient_alerts` | 04 | Header chips with tone |
| `patient_emergency_contacts` | 04 | Name, relationship, phone |
| `pharmacies` | 03, 04 | Directory (name, suburb, email, phone, address, provider number) |
| `consent_documents`, `consent_document_versions`, `patient_consents` | 03 | Version-locked consent |
| `intake_applications` | 03 | Answers, flags, declaration, status, decision |
| `practitioner_identifiers` | 02 | AHPRA, HPI-I, prescriber number, provider number, eRx ID, status |
| `practitioner_agreements` | 02 | Agreement version and attestation |
| `sops`, `sop_versions`, `sop_acknowledgements` | 02 | Versioned SOPs, per-person acknowledgement |
| `tenant_settings` (or columns on `tenants`) | 01 | Practice workflow model, retention years |

Clinic setup progress is **derived, not stored** (01 `design.md`), so it adds no table.
