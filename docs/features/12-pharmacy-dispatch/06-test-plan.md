---
doc_id: OZ-FEAT-12-TEST
title: "Pharmacy dispatch — test plan"
owner: Clinical Safety Officer + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/10-integration-boundaries.md §7, §10
  - clinic-os-secure-by-design/26-security-gates.md §6
  - clinic-os-secure-by-design/27-security-testing.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
---

# Test plan

All tests run in CI on synthetic data against a seeded two-tenant environment with a canary tenant and a
provider simulator. Every command below is complete as written. A failure in the manifest webhook matrix
is a **release blocker**.

## Functional

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| F1 | Valid signed event arrives | `200`; one `pharmacy_dispatches` row `RECEIVED`; one `webhook_events` row | `cd backend && uv run pytest tests/pharmacy/test_dispatch_receipt.py::test_signed_event_creates_receipt -v` |
| F2 | Pharmacy confirms dispense | `200`; status `DISPENSED`; `dispensed_at` and `dispensed_by` set | `cd backend && uv run pytest tests/pharmacy/test_dispatch_confirm.py::test_confirm_dispense_sets_terminal_state -v` |
| F3 | Pharmacy rejects with a reason code | `200`; status `REJECTED`; free text rejected | `cd backend && uv run pytest tests/pharmacy/test_dispatch_confirm.py::test_reject_requires_reason_code -v` |
| F4 | Unknown event type | `422`; no state change; event recorded `REJECTED` | `cd backend && uv run pytest tests/webhooks/test_webhook_schema.py::test_unknown_event_type_rejected -v` |
| F5 | List dispatches | tenant-scoped; cursor-paginated; canary tenant invisible | `cd backend && uv run pytest tests/pharmacy/test_dispatch_read.py::test_list_is_tenant_scoped_and_cursor_paginated -v` |
| F6 | Read a cross-tenant receipt | `404`, never `403` | `cd backend && uv run pytest tests/pharmacy/test_dispatch_read.py::test_cross_tenant_dispatch_returns_404 -v` |
| F7 | Inspect grants on the new tables | `webhook_events` has `{SELECT, INSERT}`; no `DELETE` on `pharmacy_dispatches` | `cd backend && uv run pytest tests/security/test_webhook_append_only_grants.py::test_pharmacy_dispatch_has_no_delete_grant -v` |
| F8 | Cancel a `DISPENSED` receipt | refused; terminal state unchanged | `cd backend && uv run pytest tests/pharmacy/test_dispatch_confirm.py::test_dispensed_cannot_be_cancelled -v` |

## Manifest webhook test matrix (`10 §7`)

| ID | Manifest case | Expected | Test command |
| --- | --- | --- | --- |
| **S1** | Forged signature | `401`; no state change | `cd backend && uv run pytest tests/webhooks/test_webhook_signature.py::test_forged_signature_returns_401 -v` |
| **S2** | Replayed webhook | `200` with **no state change** | `cd backend && uv run pytest tests/webhooks/test_webhook_replay.py::test_replay_returns_200_without_state_change -v` |
| **S3** | Unknown-tenant payload | quarantined **and alerted**; `202`; zero tenant rows | `cd backend && uv run pytest tests/webhooks/test_webhook_tenant_routing.py::test_unknown_tenant_payload_quarantined_and_alerted -v` |
| **S4** | Out-of-order event | event recorded; terminal state **not** regressed | `cd backend && uv run pytest tests/webhooks/test_webhook_ordering.py::test_out_of_order_does_not_regress_terminal_state -v` |
| **S5** | Oversized body | `413` before parsing | `cd backend && uv run pytest tests/webhooks/test_webhook_limits.py::test_oversized_body_returns_413 -v` |
| **S6** | Wrong content type | refused before parsing | `cd backend && uv run pytest tests/webhooks/test_webhook_limits.py::test_wrong_content_type_refused -v` |
| **S7** | Deduplication | exactly **one** state change per provider event id | `cd backend && uv run pytest tests/webhooks/test_webhook_dedupe.py::test_duplicate_event_yields_exactly_one_state_change -v` |

## Security

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| S8 | Timestamp outside the 5-minute window | `401`; no state change | `cd backend && uv run pytest tests/webhooks/test_webhook_signature.py::test_stale_timestamp_refused_with_401 -v` |
| S9 | Payload names tenant B on tenant A's path | tenant B affected only; path ignored | `cd backend && uv run pytest tests/webhooks/test_webhook_tenant_routing.py::test_tenant_resolved_from_payload_not_path -v` |
| S10 | Allow-listed IP with a bad signature | still `401`; allow-list is second control only | `cd backend && uv run pytest tests/webhooks/test_webhook_signature.py::test_ip_allowlist_is_second_control_only -v` |
| S11 | Unverified webhook burst | counter increments; alert fires above threshold | `cd backend && uv run pytest tests/webhooks/test_webhook_abuse.py::test_unverified_rate_alert_fires -v` |
| S12 | Failure before commit | `500`; rollback; no state change | `cd backend && uv run pytest tests/webhooks/test_webhook_commit.py::test_processing_failure_returns_500_without_state_change -v` |
| S13 | Raw body inspection across log sinks | raw body never logged; hash only | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_webhook_raw_body_never_logged -v` |
| S14 | Payload contains a URL | never dereferenced; zero egress | `cd backend && uv run pytest tests/webhooks/test_webhook_ssrf.py::test_payload_url_never_dereferenced -v` |
| S15 | App role tampers with `webhook_events` | `42501 insufficient_privilege` | `cd backend && uv run pytest tests/security/test_webhook_append_only_grants.py::test_webhook_events_append_only_grants -v` |
| S16 | Cross-tenant receipt read | `404`; zero foreign rows via raw SQL | `cd backend && uv run pytest tests/isolation/test_pharmacy_dispatch_isolation.py::test_cross_tenant_receipt_returns_404 -v` |
| S17 | Simulated provider outage | `REQUIRES_RECONCILIATION`; never `DISPENSED` | `cd backend && uv run pytest tests/webhooks/test_webhook_failure.py::test_provider_outage_never_reports_success -v` |
| S18 | Two concurrent duplicate events | exactly one receipt created | `cd backend && uv run pytest tests/webhooks/test_webhook_dedupe.py::test_concurrent_duplicate_events_create_one_receipt -v` |
| S19 | Unknown fields in the payload | `422`; nothing changes | `cd backend && uv run pytest tests/webhooks/test_webhook_schema.py::test_unknown_fields_rejected -v` |
| S20 | Missing `app.tenant_id` on the connection | zero rows returned (fail-closed `NULLIF`) | `cd backend && uv run pytest tests/isolation/test_pharmacy_dispatch_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |

## Audit

| ID | Case | Expected | Test command |
| --- | --- | --- | --- |
| A1 | Verified arrival | `integration.request` with provider, outcome, `correlation_id` | `cd backend && uv run pytest tests/webhooks/test_webhook_audit.py::test_arrival_writes_integration_request -v` |
| A2 | Committed state effect | `prescription.dispatch` with `reason = WEBHOOK_CONFIRMED` | `cd backend && uv run pytest tests/webhooks/test_webhook_audit.py::test_state_effect_records_webhook_confirmed -v` |
| A3 | Drop, duplicate and quarantine | all audited with equal fidelity to a success | `cd backend && uv run pytest tests/webhooks/test_webhook_audit.py::test_denied_and_quarantined_events_audited -v` |
| A4 | Event and log payload inspection | no clinical payload, no raw body | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_webhook_events_carry_no_clinical_payload -v` |
| A5 | Forced audit insert failure | the state change does not commit | `cd backend && uv run pytest tests/webhooks/test_webhook_audit.py::test_audit_write_failure_rolls_back_state_change -v` |

## Gate evidence mapping (`26 §6`, Gate 5)

| Gate 5 check | Evidence |
| --- | --- |
| Webhook signatures verified; replay rejected; events deduplicated on the provider identifier | S1, S2, S7, S8, S10 |
| Every outbound write carries an idempotency key and duplicates are suppressed | F1, S7, S18 (correlation with FEAT-10) |
| Timeouts become non-terminal states and a reconciliation job resolves them | S17 |
| The provider-outage playbook names an owner and a clinical fallback | S17 plus the playbook record (FEAT-13) |
| A sandbox integration test passes end to end | the full suite run against the provider sandbox |
| Vendor terms, region and sub-processor status recorded | vendor register entry (OPEN-4) |

## Traceability

F1–F8 cover R7, R8, R12–R15, R17. S1–S20 cover R1–R6, R9–R11, R16. A1–A5 cover the event catalogue in
`05-data-and-audit.md`. A test name without its command is not evidence, and a stage that cannot fail is
not a control.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| The manifest matrix cannot be final until the content-type code and reason vocabulary close (OPEN-3) | CTO + Security Lead | OPEN |
| Quarantine assertions (S3) depend on the storage choice (OPEN-2) | Security Lead + CTO | OPEN |
| Provider sandbox scenarios and their recorded output | Head of Platform | OPEN |
| Per-jurisdiction dispense-confirmation requirements | Clinical Safety Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
