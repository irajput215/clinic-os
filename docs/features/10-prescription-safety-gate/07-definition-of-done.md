---
doc_id: OZ-FEAT-10-DOD
title: "Prescription safety gate — Definition of Done and gate sign-off"
owner: Clinical Safety Officer + CTO
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/24-definition-of-done.md
  - clinic-os-secure-by-design/26-security-gates.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Definition of Done

The six parts are from doc 24. Tick only with a link to evidence.

| # | Part | Done | Evidence link |
| --- | --- | --- | --- |
| 1 | Functional: every acceptance criterion in `01-requirements.md` has a passing test | [ ] | |
| 2 | Security: deny-by-default path, permission check, tenant scope, care relationship, step-up, strict schemas | [ ] | |
| 3 | Security tests pass in CI: S1–S18, including the import lint and the bypass-token search | [ ] | |
| 4 | Audit: events emitted and verified; A1–A5; exactly one blocked event per refusal | [ ] | |
| 5 | Operations & compliance: no PHI in logs, non-terminal-age alert live, reason codes clinically approved | [ ] | |
| 6 | Deployment: image builds, scans clean, migration expand-and-contract, verified in Staging against the sandbox | [ ] | |

**No part is Done with an open High or Critical finding.** A Critical finding blocks deployment outright.

## Gate sign-off & Verification Governance

| Stage / Gate | What is Verified | Verifier (Decision Maker) | Approver | Pass Policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Import lint (S15), bypass-token search (S16), dispatch entry-point enumeration (S18), the negative dispatch matrix | CI pipeline (pytest + static checks) | Automated gate | **Hard block on failure** |
| **Gate 4 (APIs & clinical safety)** | The gate blocks every negative case; no frontend or request field bypasses it; unknown fields rejected; error envelope leaks nothing | **Security Lead** | **CTO** + **Clinical Safety Officer** | **NO conditional pass for the safety gate** |
| **Gate 6 (Production)** | The five security test categories; the gate deployed to Staging against the sandbox; the reconciliation job verified | **Security Lead** | **Head of Platform** + CTO | Available for a **High** finding with a compensating control and expiry. **Not available for a Critical finding** |
| **Clinical sign-off** | Reason-code vocabulary, the refusal message, and the reconciliation threshold | **Clinical Safety Officer** | Practice Owner | **Cannot be waived** |
| **Any gate change** | A change to the gate module, its reason codes, or the retry policy | Security Lead | CTO + CSO | **Gate 6 re-run required** |

**No self-approval.** The person who delivered the work never signs its gate.

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| No dispatch without an `ACTIVE` approval at the grain | Server-side gate inside the dispatch transaction, evaluated at `date_of_service` | `evaluateDispatchGate(ctx)` — the only caller of the provider client | F1–F9, S1, S2 | Clinical Safety Officer | planned |
| The frontend cannot override the gate | No bypass flag or override parameter; the message is rendered from the response | Token search plus import lint in CI | S4, S15, S16 | Security Lead | planned |
| Only one code path reaches the prescription rail | One exported entry point and a repository import-lint rule | `no-restricted-imports` equivalent, fail-the-build | S15, S18 | CTO | planned |
| A timeout is never reported as success | Unknown outcome maps to `REQUIRES_RECONCILIATION` with a named resolver | Reconciliation job, 5-minute cadence, 24-hour escalation | F10, S10, S12 | CTO | planned |
| Duplicate dispatch is prevented by the database | Server-computed idempotency key reused on every retry | `UNIQUE (tenant_id, idempotency_key)` | S5, S6 | CTO | planned |
| An unauditable dispatch cannot occur | Audit write in the same transaction; failure rolls back | `test_audit_write_failure_rolls_back` | S11, A1, A2 | Security Lead | planned |
| Blocked attempts are security-relevant and recorded | `prescription.dispatch_blocked` on every refusal, never suppressed | Gate writes its own event before returning | A1, A4 | Security Lead | planned |
| Clinical content stays out of the audit trail | Audit records the action, not the content; payload hash only | `test_audit_carries_no_clinical_payload` | A4, A5 | Clinical Safety Officer | planned |
| Every gate change is clinically reviewed | Gate 6 re-run with CSO approval | Gate 6 record per release | gate record | Clinical Safety Officer | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-1 e-prescribing conformance (register, certified party, sunset dates) | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-2 Schedule 8 and real-time prescription monitoring per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 duplicate-dispatch window for step 9 | Clinical Safety Officer | OPEN |
| OPEN-4 reconciliation threshold and 24-hour escalation | Clinical Safety Officer | OPEN |
| OPEN-6 `valid_to` boundary (D-006 OPEN-2) changes step 8 for the final day | Clinical Safety Officer | OPEN |
| OPEN-7 signing-key custody once D-003 closes | CTO + Security Lead | OPEN |
