---
doc_id: OZ-FEAT-10-REQ
title: "Prescription safety gate — requirements"
owner: Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/02-security-architecture.md
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 06-test-plan.md
---

# Prescription safety gate: requirements

## Purpose

The single server-side control enforcing **INV-2**: **no prescription is dispatched without an `ACTIVE`
TGA approval at the approval grain.** A missing or bypassable gate permits a Schedule 8 or unapproved
therapeutic good to be dispensed without regulatory authorisation — criminal and civil liability under
the *Therapeutic Goods Act 1989* (Cth).

Source: `09-prescription-safety-gate.md` §1; `02-security-architecture.md` §2.1.

## The grain

```
PATIENT ID + TGA CATEGORY + DOSAGE FORM + TEMPORAL VALIDITY INTERVAL
```

Evaluated at **`date_of_service`**, never the system clock, in `Australia/Sydney`. Never patient-level
alone, never medicine-level alone, never a static boolean.

## Functional requirements

| ID | Requirement | Acceptance criterion (testable) |
| --- | --- | --- |
| R1 | The gate has exactly one entry point and is callable from exactly one route | `POST /api/v1/prescriptions/{id}/dispatch` is the only caller; a repository lint reports zero other imports of the provider client |
| R2 | The gate takes no bypass parameter | A token search finds no `skip`, `force` or `override` argument in the gate module |
| R3 | There is no feature flag on the gate | No configuration key can disable it; a flag affecting it requires CSO approval and a Gate 4 re-run |
| R4 | Evaluation follows a fixed order of eleven steps | Steps run in order; a failure at step *n* prevents steps *n+1…11* |
| R5 | Dispatch is refused unless an `ACTIVE` approval exists at the grain covering `date_of_service` | `422`, reason code names the failing dimension |
| R6 | A refusal makes **no outbound call** | The provider adapter log contains no request for a refused dispatch |
| R7 | A refusal is a security event and is always audited | Exactly one `prescription.dispatch_blocked` per refused request, with a `block_reason`; never suppressed |
| R8 | A client-supplied approval, status or state is ignored | Sending `approval_id`, `status` or `state` returns `422` (unknown field) and changes nothing |
| R9 | The frontend cannot influence the decision | A hand-crafted request with no UI state is refused identically to a UI-originated one |
| R10 | Signing and dispatch require fresh step-up | A stale `auth_time` returns `401 step_up_required` |
| R11 | Dispatch is idempotent per intent | A retry with the same key produces one prescription and one provider call |
| R12 | The idempotency key is computed server-side | Client header is hashed into the key, never used raw |
| R13 | A timeout becomes an explicit unknown state | `REQUIRES_RECONCILIATION`; never `SUCCESS` or `FAILED` |
| R14 | Reconciliation resolves every non-terminal state in both directions | Job moves the row to `DISPATCHED` or `FAILED` with `reason = RECONCILED` |
| R15 | Reconciliation runs with explicit tenant context | A job without tenant context fails loudly rather than running unscoped |
| R16 | A concurrent approval revocation cannot interleave between check and insert | The approval row is read `FOR SHARE`; dispatch is blocked |
| R17 | An audit write failure aborts the dispatch | Forcing the audit insert to fail leaves no dispatch attempt and no provider call |
| R18 | The gate records the decision before returning it, including refusals | The event exists in the same transaction as the decision |

## Out of scope for the MVP

- Provider transport mechanics — Parchment adapter, retry, circuit breaker (FEAT-13)
- Prescription authoring, drafting and signing (FEAT-11)
- Approval creation, verification and revocation (FEAT-08)
- Pharmacy-side receipt and confirmation (FEAT-12)

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | E-prescribing conformance: which register, which certified party, which sunset dates | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-2 | Schedule 8 and real-time prescription monitoring mandatory checks per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 | The duplicate-dispatch window for the clinical validation step | Clinical Safety Officer | OPEN |
| OPEN-4 | Reconciliation threshold (default 15 minutes) and the 24-hour escalation | Clinical Safety Officer | OPEN |
| OPEN-5 | Whether a pharmacist-initiated dispatch path is in pilot scope | Head of Product | OPEN |
| OPEN-6 | The `valid_to` boundary (D-006 OPEN-2) changes gate step 8 for the final day | Clinical Safety Officer | OPEN |
| OPEN-7 | Signing-key custody, once D-003 is decided | CTO + Security Lead | OPEN |
