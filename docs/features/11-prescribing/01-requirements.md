---
doc_id: OZ-FEAT-11-REQ
title: "Prescribing — requirements"
owner: Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/21-technical-design.md
  - clinic-os-secure-by-design/20-product-requirements.md §7
  - clinic-os-secure-by-design/22-user-stories.md US-21…US-26
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# Prescribing: requirements

## Purpose

Let an Authorised Prescriber — or a Nurse staging a draft on their behalf — author, review and sign a
prescription so that the **FEAT-10** safety gate can evaluate it and release it to the provider. This
module owns the prescription record, its identity-bound signature and its server-managed state. It does
**not** own the gate decision, the provider transport, or the pharmacy receipt.

Sources: `09-prescription-safety-gate.md` §6; `20-product-requirements.md` §7; `21-technical-design.md` §9.

## Functional requirements

| ID | Requirement | Acceptance criterion (testable) | Evidence (pytest) |
| --- | --- | --- | --- |
| **R1** | Stage a prescription for a patient in the caller's tenant | `POST` returns `201` in state `DRAFT`; `tenant_id` resolved from the session, never the body | `tests/prescribing/test_lifecycle.py::test_stage_draft_tenant_from_session` |
| **R2** | Strict body schema on every write | Unknown fields — including `state`, `tenant_id`, `prescriber_id` — return `422` and write nothing | `tests/prescribing/test_validation.py::test_stage_rejects_unknown_fields` |
| **R3** | A draft is editable until signed | `PATCH` succeeds only in `DRAFT`; `prescription.modify` records changed field **names**, never values | `tests/prescribing/test_lifecycle.py::test_draft_editable_until_signed` |
| **R4** | Signing requires `prescription:sign`, the prescriber of record and fresh step-up | Stale `auth_time` returns `401 step_up_required`; a different practitioner returns `403`; success sets `SIGNED` | `tests/prescribing/test_signing.py::test_sign_requires_step_up_and_prescriber_of_record` |
| **R5** | `SIGNED` is immutable; a correction is an addendum | Any `UPDATE` of a signed payload or signature is refused; an addendum creates a new version referencing the original, whose bytes are unchanged | `tests/prescribing/test_immutability.py::test_signed_is_immutable_and_addendum_preserves_original` |
| **R6** | A concurrent sign of one draft produces one signed prescription | Two simultaneous sign requests yield exactly one `SIGNED` row and one `prescription.sign` event | `tests/prescribing/test_signing.py::test_concurrent_sign_produces_one_signed` |
| **R7** | Transitions are server-managed | A client-supplied target `state` is rejected as an unknown field (`422`) and changes nothing | `tests/prescribing/test_state.py::test_client_supplied_state_rejected` |
| **R8** | Every transition is validated against the state machine | Any transition outside the allowed set returns `409 INVALID_STATE_TRANSITION` and is audited | `tests/prescribing/test_state.py::test_illegal_transition_409_and_audited` |
| **R9** | Dispatch is invoked only through the FEAT-10 gate on `SIGNED → QUEUED` | This module contains no gate logic; the route calls the gate and records its decision | `tests/static/test_state_transition_entry_points.py::test_dispatch_route_only_calls_gate` |
| **R10** | A `BLOCKED` prescription may be re-submitted without re-signing | After the approval is obtained, the retry reaches `QUEUED` with no new signature event | `tests/prescribing/test_state.py::test_blocked_resubmit_without_resigning` |
| **R11** | Cancel before dispatch requires a reason | `POST .../cancel` moves `DRAFT` or `SIGNED` to `CANCELLED`; missing reason returns `422` | `tests/prescribing/test_lifecycle.py::test_cancel_requires_reason` |
| **R12** | Cross-tenant access returns `404`, never `403` | A foreign-tenant prescription id is indistinguishable from a non-existent one | `tests/isolation/test_prescribing_isolation.py::test_cross_tenant_returns_404` |
| **R13** | Every client-initiated write accepts an `Idempotency-Key` | A duplicate returns the original result; one row exists | `tests/prescribing/test_idempotency.py::test_duplicate_write_returns_original` |
| **R14** | Records are never hard-deleted and events are append-only | No `DELETE` endpoint; `DELETE`/`UPDATE` on `prescription_events` and `prescription_state_history` is denied by grant | `tests/security/test_prescribing_append_only_grants.py::test_events_and_history_append_only` |
| **R15** | Denied and failed attempts are audited with equal fidelity | A refused sign, an illegal transition and a refused cross-tenant read each emit their event | `tests/prescribing/test_audit.py::test_denied_attempts_audited` |

## Out of scope for the MVP

- The gate's decision logic, reason codes and idempotency design — **FEAT-10** (`10-prescription-safety-gate/`).
- Provider transport, retry, circuit breaker and the Parchment adapter — **FEAT-13**.
- Pharmacy receipt, confirmation webhooks and reconciliation — **FEAT-12**.
- Approval creation, verification and revocation — **FEAT-08**.

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | **State-name conflict, not resolved here.** `09-prescription-safety-gate.md` §6 names `QUEUED`/`DISPATCHED`; `21-technical-design.md` §9 and US-24…US-26 name `SUBMITTING`/`SUBMITTED`/`CONFIRMED`. This document uses `QUEUED`/`DISPATCHED` to stay consistent with FEAT-10. A rename is a gate change and requires a Gate 4 re-run | Clinical Safety Officer + CTO | OPEN |
| OPEN-2 | Whether the approval must also be checked at **sign** time, and whether a sign-time block is clinically acceptable (`09` open item 2) | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-3 | E-prescribing conformance: which register, which certified party, which sunset dates | CTO | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-4 | Schedule 8 and real-time prescription monitoring obligations per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | Controlled vocabularies for medicine, dosage form and TGA category, and their owner (`09` open item 1) | Clinical Safety Officer | OPEN |
| OPEN-6 | Whether a missing Authorised Prescriber report must block prescribing (`09` open item 7) | TGA Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-7 | Role and permission names align to `06-authentication-rbac.md` before build | Security Lead | OPEN |
