---
doc_id: OZ-FEAT-11-TEST
title: "Prescribing — test plan"
owner: Clinical Safety Officer + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-11
phase: 03-phase-3-eprescribing
gate: [4, 5]
source:
  - clinic-os-secure-by-design/09-prescription-safety-gate.md §11
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/26-security-gates.md §5
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data against a seeded two-tenant environment with a **canary tenant**, and
every named test is run with its exact command. A failing security test blocks merge. Commands run from the
repository root; the working directory is `cd backend`.

## Functional

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| F1 | Stage a valid draft | `201`, state `DRAFT`, tenant from session | `cd backend && uv run pytest tests/prescribing/test_lifecycle.py::test_stage_draft_tenant_from_session -v` |
| F2 | Missing clinical field | `422`, zero rows written | `cd backend && uv run pytest tests/prescribing/test_validation.py::test_stage_rejects_missing_fields -v` |
| F3 | Modify a draft | `200`, changed field **names** recorded, no values | `cd backend && uv run pytest tests/prescribing/test_lifecycle.py::test_draft_modify_records_field_names -v` |
| F4 | Modify after signing | `409`, `prescription.modify` refused and audited | `cd backend && uv run pytest tests/prescribing/test_immutability.py::test_modify_after_signing_refused -v` |
| F5 | Cancel before dispatch with a reason | `200`, state `CANCELLED`, `prescription.reject` | `cd backend && uv run pytest tests/prescribing/test_lifecycle.py::test_cancel_requires_reason -v` |
| F6 | `BLOCKED` then approval obtained | retry reaches `QUEUED` with **no** new signature event | `cd backend && uv run pytest tests/prescribing/test_state.py::test_blocked_resubmit_without_resigning -v` |
| F7 | Duplicate write with the same idempotency key | one row; the original result is returned | `cd backend && uv run pytest tests/prescribing/test_idempotency.py::test_duplicate_write_returns_original -v` |
| F8 | Concurrent sign of one draft | exactly one `SIGNED` row and one `prescription.sign` | `cd backend && uv run pytest tests/prescribing/test_signing.py::test_concurrent_sign_produces_one_signed -v` |
| F9 | Cross-tenant read | `404 Not Found` | `cd backend && uv run pytest tests/isolation/test_prescribing_isolation.py::test_cross_tenant_returns_404 -v` |
| F10 | Read the state history | ordered transitions returned | `cd backend && uv run pytest tests/prescribing/test_lifecycle.py::test_history_is_ordered -v` |

## Security

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| S1 | **A signed prescription is immutable** — direct `UPDATE` of a payload field on a `SIGNED` row | refused `SIGNED_IS_IMMUTABLE`; row unchanged | `cd backend && uv run pytest tests/prescribing/test_immutability.py::test_signed_is_immutable -v` |
| S2 | **Addendum preserves the original byte-for-byte** — create an addendum, then compare the original row | new version with `supersedes_id`; original byte-identical | `cd backend && uv run pytest tests/prescribing/test_immutability.py::test_addendum_creates_version_and_preserves_original -v` |
| S3 | **Signing requires step-up** — sign with a stale `auth_time` | `401 step_up_required`; state stays `DRAFT` | `cd backend && uv run pytest tests/prescribing/test_signing.py::test_sign_requires_step_up -v` |
| S4 | Sign as a practitioner other than the prescriber of record | `403`; audited | `cd backend && uv run pytest tests/prescribing/test_signing.py::test_sign_as_other_prescriber_403 -v` |
| S5 | **Unknown-field rejection for a supplied state** — body carries `state` | `422` unknown field; nothing changes | `cd backend && uv run pytest tests/prescribing/test_state.py::test_client_supplied_state_rejected -v` |
| S6 | **Every illegal transition returns `409` and is audited** — parametrised over the full transition matrix | `409 INVALID_STATE_TRANSITION` for each; one denied event each | `cd backend && uv run pytest tests/prescribing/test_state.py::test_every_illegal_transition_409_and_audited -v` |
| S7 | Append-only grants inspection on the three tables | `prescription_events` and `prescription_state_history` have `{SELECT, INSERT}`; `prescriptions` has no `DELETE`/`TRUNCATE` | `cd backend && uv run pytest tests/security/test_prescribing_append_only_grants.py::test_events_and_history_append_only -v` |
| S8 | App-role `UPDATE`/`DELETE` on `prescription_events` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_prescribing_append_only_grants.py::test_event_mutation_denied -v` |
| S9 | Missing tenant setting on the connection | zero rows returned (fail-closed `NULLIF`) | `cd backend && uv run pytest tests/isolation/test_prescribing_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| S10 | Connection-pool reuse: tenant A then tenant B | no context or session leakage | `cd backend && uv run pytest tests/isolation/test_prescribing_isolation.py::test_pool_reuse_no_leakage -v` |
| S11 | Role × endpoint permission matrix | only authorised roles succeed; unauthorised audited | `cd backend && uv run pytest tests/security/test_prescribing_rbac.py::test_role_endpoint_matrix -v` |
| S12 | Quantity or repeat out of bounds; `schedule8_flag` supplied in the body | `422`; flag is not client-settable | `cd backend && uv run pytest tests/prescribing/test_validation.py::test_quantity_repeat_bounds_and_schedule8_not_client_set -v` |
| S13 | **Log redaction** — sentinel values in every `HIGHLY_SENSITIVE` field | never appear in any log sink or stack trace | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_prescribing_payloads_contain_no_phi -v` |
| S14 | Sensitive-write rate limit exceeded | `429 Too Many Requests` | `cd backend && uv run pytest tests/security/test_prescribing_rate_limits.py::test_sensitive_write_rate_limit -v` |

## Audit

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| A1 | Draft created | one `prescription.create` with the full envelope | `cd backend && uv run pytest tests/prescribing/test_audit.py::test_create_event_envelope -v` |
| A2 | Signature applied | `prescription.sign` with `step_up = true` and `prescriber_id`; no clinical payload | `cd backend && uv run pytest tests/prescribing/test_audit.py::test_sign_event_fields_no_payload -v` |
| A3 | Illegal transition | a denied event is written with the attempted transition | `cd backend && uv run pytest tests/prescribing/test_audit.py::test_illegal_transition_audited -v` |
| A4 | Refused cross-tenant read | audited with the same fidelity as an allowed read | `cd backend && uv run pytest tests/prescribing/test_audit.py::test_denied_attempts_audited -v` |
| A5 | Forced audit-write failure during sign | the operation does not complete (fail closed) | `cd backend && uv run pytest tests/prescribing/test_audit.py::test_audit_write_failure_aborts_sign -v` |

## Gate evidence mapping

| Gate check | Evidence |
| --- | --- |
| Gate 4 — input validation rejects unknown fields and prevents mass assignment | S5, S12 |
| Gate 4 — cross-tenant access fails through every route | F9, S9, S10 |
| Gate 4 — error responses use the standard envelope and leak no stack trace | F2, F4, S5, S6 |
| Gate 4 — the prescription safety gate cannot be bypassed (`26 §5`) | F6; the FEAT-10 suite; `test_dispatch_route_only_calls_gate` |
| Gate 5 — integration boundaries: no provider client imported here | the FEAT-13 import lint |
| Gate 2 — append-only enforcement and immutability proof | S1, S2, S7, S8 |

## Traceability

F1–F10 cover R1–R6, R10, R11, R13. S1–S14 cover R2, R4–R9, R12, R14. A1–A5 cover R8, R15 and the event
catalogue in 05-data-and-audit.md. A test name without its command is not evidence, and a stage that cannot
fail is not a control.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| The transition-matrix fixture must be generated from the state machine so a new state cannot be added without a test | CTO | OPEN |
| Schedule 8 and real-time prescription monitoring cases per jurisdiction | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Concurrency test needs a deterministic interleaving harness | Head of Platform | OPEN |
