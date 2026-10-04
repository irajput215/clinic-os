---
doc_id: OZ-FEAT-10-TEST
title: "Prescription safety gate — test plan"
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
  - clinic-os-secure-by-design/27-security-testing.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data against a seeded two-tenant environment with a **canary tenant**.
**A failure in any test in the gate matrix is a release blocker** and requires Gate 6 sign-off to
override, recorded in the risk register.

## Functional

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| F1 | No approval at the grain | `422`, `NO_ACTIVE_TGA_APPROVAL_FOR_CATEGORY_AND_DOSAGE_FORM`, one blocked event | `cd backend && uv run pytest tests/gate/test_gate_blocked.py::test_blocked_without_approval -v` |
| F2 | `EXPIRED` approval | `422 APPROVAL_EXPIRED` | `cd backend && uv run pytest tests/gate/test_gate_blocked.py::test_expired_approval_blocks -v` |
| F3 | `REVOKED` approval | `422 APPROVAL_REVOKED` | `cd backend && uv run pytest tests/gate/test_gate_blocked.py::test_revoked_approval_blocks -v` |
| F4 | `PENDING` approval | `422 APPROVAL_PENDING_VERIFICATION` | `cd backend && uv run pytest tests/gate/test_gate_blocked.py::test_pending_approval_blocks -v` |
| F5 | Superseded approval replaced by a current one | lookup returns the newest record and names it in the event | `cd backend && uv run pytest tests/gate/test_gate_match.py::test_superseded_resolves_to_current -v` |
| F6 | Dosage-form mismatch | lookup key includes the dosage form; blocked | `cd backend && uv run pytest tests/gate/test_gate_match.py::test_dosage_form_mismatch_blocks -v` |
| F7 | Category mismatch | lookup key includes the category; blocked | `cd backend && uv run pytest tests/gate/test_gate_match.py::test_category_mismatch_blocks -v` |
| F8 | Patient mismatch | lookup key includes the patient; blocked | `cd backend && uv run pytest tests/gate/test_gate_match.py::test_patient_mismatch_blocks -v` |
| F9 | Valid approval covering the service date | `201`, prescription reaches `QUEUED` then `DISPATCHED` | `cd backend && uv run pytest tests/gate/test_gate_pass.py::test_valid_dispatch_succeeds -v` |

## Security

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| S1 | Canary-tenant approval does not satisfy the lookup and is not disclosed | blocked, no disclosure | `cd backend && uv run pytest tests/gate/test_gate_isolation.py::test_cross_tenant_approval_invisible -v` |
| S2 | Boundary at 23:59 on `valid_to` and 00:01 the next day, in `Australia/Sydney` | per OPEN-6; interim half-open excludes the `valid_to` day | `cd backend && uv run pytest tests/gate/test_gate_match.py::test_validity_boundary_sydney -v` |
| S3 | Hand-crafted request with no UI state | refused identically to a UI-originated one | `cd backend && uv run pytest tests/gate/test_gate_no_bypass.py::test_direct_api_call_blocked -v` |
| S4 | Body supplies `approval_id`, `status` or `state` | `422` unknown field; nothing changes | `cd backend && uv run pytest tests/gate/test_gate_no_bypass.py::test_unknown_fields_rejected -v` |
| S5 | Duplicate request with the same idempotency key | exactly one provider call and one `dispatch_attempts` row | `cd backend && uv run pytest tests/gate/test_gate_idempotency.py::test_double_dispatch_same_key_dispatches_once -v` |
| S6 | Client-supplied `Idempotency-Key` header | hashed into the key, never used raw; no cross-tenant collision | `cd backend && uv run pytest tests/gate/test_gate_idempotency.py::test_client_key_is_hashed -v` |
| S7 | Dispatch after session revocation | `401`, **no provider call** | `cd backend && uv run pytest tests/gate/test_gate_auth.py::test_dispatch_after_revocation_401 -v` |
| S8 | Role without `prescription:dispatch`, with step-up | `403`, audited | `cd backend && uv run pytest tests/gate/test_gate_auth.py::test_role_without_permission_403 -v` |
| S9 | Stale step-up | `401 step_up_required` | `cd backend && uv run pytest tests/gate/test_gate_auth.py::test_stale_step_up_401 -v` |
| S10 | Simulated provider timeout | `result = UNKNOWN`, state `REQUIRES_RECONCILIATION`, no success state | `cd backend && uv run pytest tests/gate/test_gate_reconciliation.py::test_timeout_produces_requires_reconciliation -v` |
| S11 | Forced audit insert failure | no dispatch attempt and **no provider call** | `cd backend && uv run pytest tests/gate/test_gate_audit.py::test_audit_write_failure_rolls_back -v` |
| S12 | Reconciliation job resolves a confirmed unknown outcome | `DISPATCHED`, `reason = RECONCILED` | `cd backend && uv run pytest tests/gate/test_gate_reconciliation.py::test_reconciliation_resolves_unknown -v` |
| S13 | Reconciliation job re-runs on a resolved row | not re-dispatched | `cd backend && uv run pytest tests/gate/test_gate_reconciliation.py::test_reconciliation_does_not_duplicate -v` |
| S14 | Concurrent approval revocation during a gate check | dispatch blocked; `FOR SHARE` holds | `cd backend && uv run pytest tests/gate/test_gate_concurrency.py::test_concurrent_revocation_blocks -v` |
| S15 | Import lint: any module outside the gate importing the provider client | zero violations | `cd backend && uv run pytest tests/static/test_import_boundaries.py::test_no_other_module_imports_provider_client -v` |
| S16 | Bypass-token search for `skip`, `force`, `override` in the gate module | zero hits | `cd backend && uv run pytest tests/static/test_import_boundaries.py::test_gate_rejects_bypass_params -v` |
| S17 | Reconciliation job run without tenant context | fails loudly, does not run unscoped | `cd backend && uv run pytest tests/gate/test_gate_reconciliation.py::test_reconciliation_requires_tenant_context -v` |
| S18 | Every dispatch entry point in the codebase | each one enumerated and each calls the gate | `cd backend && uv run pytest tests/static/test_dispatch_entry_points.py -v` |

## Audit

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| A1 | One refused request | exactly **one** `prescription.dispatch_blocked` with the correct reason | `cd backend && uv run pytest tests/gate/test_gate_audit.py::test_blocked_attempt_audited_once -v` |
| A2 | Successful dispatch | `prescription.dispatch` with `approval_id` and `idempotency_key` | `cd backend && uv run pytest tests/gate/test_gate_audit.py::test_dispatch_event_fields -v` |
| A3 | Timeout then resolution | `result = UNKNOWN`, then `reason = RECONCILED` with the original `correlation_id` | `cd backend && uv run pytest tests/gate/test_gate_audit.py::test_unknown_then_reconciled -v` |
| A4 | Event payload inspection | no medicine, dose, quantity or direction in any event | `cd backend && uv run pytest tests/gate/test_gate_audit.py::test_audit_carries_no_clinical_payload -v` |
| A5 | Sentinel values in prescription fields | never appear in any log sink | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py -v` |

## Gate evidence mapping

| Gate check | Evidence |
| --- | --- |
| Gate 4 — "the prescription safety gate blocks every negative case and no frontend or request field can bypass it" | F1–F8, S3, S4, S15, S16, S18; the negative dispatch matrix |
| Gate 4 — cross-tenant access fails through every route | S1 |
| Gate 4 — input validation rejects unknown fields and prevents mass assignment | S4 |
| Gate 4 — error responses use the standard envelope and leak no stack trace | F1–F8 assertions |
| Gate 6 — the five security test categories pass | the full suite in Staging |
| Gate 6 — SAST, dependency, container and secret scans clean of Critical | CI scan reports |

## Traceability

F1–F9 cover R5, R8, R9, R14. S1–S18 cover R1–R4, R6, R7, R10–R17. A1–A5 cover R7, R18.
A test name without its command is not evidence, and a stage that cannot fail is not a control.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Nightly reconciliation schedule and its environment | Head of Platform | OPEN |
| Generate the negative dispatch matrix from the reason-code vocabulary so a new code cannot be added without a test | CTO | OPEN |
| Schedule 8 and real-time prescription monitoring cases per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
