---
doc_id: OZ-FEAT-11-DOD
title: "Prescribing — Definition of Done and gate sign-off"
owner: Clinical Safety Officer + CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md §5
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in 01-requirements.md has a passing test | [ ] | F1–F10 in 06-test-plan.md |
| 2 | Security: deny-by-default path, RLS with `NULLIF` and `FORCE`, permissions, step-up, strict schemas, server-managed transitions | [ ] | S1–S14 |
| 3 | Security tests pass in CI: S1–S14, including the immutability, transition-matrix and log-redaction tests | [ ] | CI run for `tests/prescribing` + `tests/security` |
| 4 | Audit: events emitted and verified; A1–A5; denied attempts audited with equal fidelity | [ ] | A1–A5 |
| 5 | Operations & compliance: classification applied, no PHI in logs, residency register updated, alerts present | [ ] | 05-data-and-audit.md; test S13 |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging | [ ] | CI scan report; Staging run |

**No part is Done with an open High or Critical finding.** A Critical finding blocks deployment outright.

## Gate sign-off & Verification Governance

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Immutability (S1, S2), append-only grants (S7, S8), the full illegal-transition matrix (S6), unknown-field rejection (S5) | CI pipeline (pytest + static checks) | Automated gate | **Hard block on failure** |
| **Gate 4 (APIs & RBAC)** | Deny-by-default path; cross-tenant `404`; strict schemas; step-up on sign and dispatch; the FEAT-10 gate is the only dispatch path | **Security Lead** | **CTO** + **Clinical Safety Officer** | **The safety gate admits NO conditional pass** (`26 §5`) |
| **Gate 5 (Integrations)** | No provider client is imported by this module; the dispatch route calls the gate only | **Security Lead** | **Head of Platform** | No conditional pass for the safety boundary |
| **Clinical sign-off** | The transition matrix (`BLOCKED` re-submit without re-signing), the cancel-reason rule, and the addendum rule | **Clinical Safety Officer** | Practice Owner | **Cannot be waived** |
| **Any state name or transition change** | A rename or a new/removed transition, including the `QUEUED`/`DISPATCHED` vs `SUBMITTING`/`SUBMITTED`/`CONFIRMED` conflict | Security Lead | CTO + CSO | **Gate 4 re-run required** |

**No self-approval.** The person who delivered the work never signs its gate.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| A signed prescription cannot be altered | Immutability trigger plus addendum-as-new-version | `trg_prescriptions_lock_signed` raising `SIGNED_IS_IMMUTABLE`; `supersedes_id` | S1, S2 | Clinical Safety Officer | planned |
| A caller cannot choose the next state | Transition table server-side; no target-state parameter | `409 INVALID_STATE_TRANSITION`; strict schema | S5, S6 | CTO | planned |
| Signing is identity-bound and step-up gated | Session-bound signer equal to `prescriber_id`; fresh step-up | `prescription.sign` with `step_up = true` | S3, S4, A2 | Security Lead | planned |
| A prescription is never hard-deleted | `REVOKE DELETE, TRUNCATE`; no delete endpoint | grant inspection | S7 | Privacy Officer | planned |
| Event history is append-only | `GRANT SELECT, INSERT` only on `prescription_events` and `prescription_state_history` | `information_schema.role_table_grants` query plus negative SQL | S7, S8 | Security Lead | planned |
| A clinic cannot see another clinic's prescriptions | RLS with `NULLIF(...)` and `FORCE`; `404` at the boundary | `pol_prescriptions_tenant_isolation` | S9, S10, F9 | CTO | planned |
| Clinical content stays out of logs and the audit trail | `HIGHLY_SENSITIVE` never logged; audit records field names only | redaction pipeline; `detail` redacted | S13, A2 | Privacy Officer | planned |
| No dispatch without an `ACTIVE` approval at the grain | FEAT-10 gate, invoked on `SIGNED → QUEUED`; this module owns no gate logic | call to `evaluateDispatchGate`; import lint | F6; FEAT-10 F1–F9 | Clinical Safety Officer | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 state-name conflict (`QUEUED`/`DISPATCHED` vs `SUBMITTING`/`SUBMITTED`/`CONFIRMED`) — a rename is a Gate 4 change | Clinical Safety Officer + CTO | OPEN |
| OPEN-2 whether the approval is also checked at sign time | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 e-prescribing conformance (register, certified party, sunset dates) | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-4 Schedule 8 and real-time prescription monitoring per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 controlled vocabularies for medicine, dosage form and TGA category | Clinical Safety Officer | OPEN |
| Column-name divergence between `04 §3.8` and `12 §3` (`dosage`/`frequency`/`route`/`duration` vs `dose_instruction`/`quantity`/`repeats`/`schedule8_flag`) | CTO + CSO | OPEN |
| Audit action names absent from `07 §1` (`PRESCRIPTION_RECONCILED`, `RECONCILIATION_RUN`, the US-25 webhook labels) | CTO + Clinical Safety Officer | OPEN |
| Retention period for prescription records and audit events per jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
