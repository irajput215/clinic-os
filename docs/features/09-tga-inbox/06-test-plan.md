---
doc_id: OZ-FEAT-09-TEST
title: "TGA inbox — test plan"
owner: Clinical Safety Officer + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md §2, §3, §4, §9, §10, §12
  - clinic-os-secure-by-design/27-security-testing.md
  - clinic-os-secure-by-design/03-threat-model.md §7, §13
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data against a seeded two-tenant environment with a **canary tenant**.
A failing security test blocks merge. A test name without its command is not evidence.

```bash
cd backend && uv run pytest tests/inbox tests/isolation/test_tga_inbox_isolation.py \
  tests/security/test_tga_inbox_validation.py tests/security/test_tga_inbox_grants.py -v
```

## Functional

| ID | Case | Expected | Command |
| --- | --- | --- | --- |
| **F1** | Sender authentication recorded | SPF, DKIM and DMARC results stored on the message row and returned to the reviewer | `cd backend && uv run pytest tests/inbox/test_intake.py::test_sender_auth_results_recorded -v` |
| **F2** | Unknown sender | Quarantined; **no attachment extracted**; message marked quarantined with the reason | `cd backend && uv run pytest tests/inbox/test_intake.py::test_unknown_sender_quarantined -v` |
| **F3** | Attachment limits | An 11th attachment refused; a > 25 MB file returns `413` before storage; `a.pdf.exe` rejected | `cd backend && uv run pytest tests/inbox/test_validation.py::test_attachment_limits_and_double_extension -v` |
| **F4** | Text layer present | Text extracted from the layer; OCR is not invoked | `cd backend && uv run pytest tests/inbox/test_extraction.py::test_text_layer_preferred_over_ocr -v` |
| **F5** | Encrypted / password-protected PDF | Not cracked; routed to manual review with `ENCRYPTED` / `PASSWORD_PROTECTED`, no text extracted | `cd backend && uv run pytest tests/inbox/test_extraction.py::test_encrypted_document_not_cracked_routes_to_review -v` |
| **F6** | **Low-confidence routing names the failing fields** | Composite below `tga_inbox_confidence_threshold` stays `PENDING`; the queue item names each field below the `0.80` floor, not just the composite | `cd backend && uv run pytest tests/inbox/test_confidence.py::test_low_confidence_routes_and_names_failing_fields -v` |
| **F7** | **Per-field provenance** | Every extracted value carries `page_number` and a `region`; a value without provenance is rejected | `cd backend && uv run pytest tests/inbox/test_extraction.py::test_every_field_has_page_and_region_provenance -v` |
| **F8** | Ambiguous digit in the approval number (`0`/`O`, `1`/`I`) | That field's confidence falls and the record routes to review | `cd backend && uv run pytest tests/inbox/test_extraction.py::test_ambiguous_digit_lowers_confidence_and_routes -v` |
| **F9** | Un-extractable field | Left empty and marked `NOT_FOUND`; never guessed | `cd backend && uv run pytest tests/inbox/test_extraction.py::test_missing_field_is_not_found_never_guessed -v` |
| **F10** | Multi-approval letter | Split into one review item per candidate grain; never one item covering several grains | `cd backend && uv run pytest tests/inbox/test_routing.py::test_multi_approval_letter_splits_per_grain -v` |
| **F11** | Letter for an unknown patient | Routed to the manual-resolution queue with the candidate list and reasons | `cd backend && uv run pytest tests/inbox/test_matching.py::test_unknown_patient_routes_to_manual_resolution -v` |
| **F12** | Two candidates within 0.05 | Both presented; an explicit choice is required; no candidate is pre-selected | `cd backend && uv run pytest tests/inbox/test_matching.py::test_close_candidates_require_explicit_choice -v` |
| **F13** | Duplicate ingestion (same `provider_message_id` or content hash) | No second object, no duplicate approval; linkage recorded | `cd backend && uv run pytest tests/inbox/test_idempotency.py::test_duplicate_ingestion_links_not_duplicates -v` |
| **F14** | Duplicate grain already exists | Enters the supersede flow; no second `ACTIVE` row | `cd backend && uv run pytest tests/inbox/test_approval_write.py::test_duplicate_grain_enters_supersede -v` |
| **F15** | **Reprocess idempotency** | Reprocessing from the extraction stage creates a new attempt keyed by `extractor_version`; prior results unchanged; one approval, not two | `cd backend && uv run pytest tests/inbox/test_idempotency.py::test_reprocess_is_idempotent -v` |
| **F16** | Queue order and ageing | Oldest first with score shown; an item older than 4 h raises the CSO alert; a second concurrent claim returns `409` | `cd backend && uv run pytest tests/inbox/test_queue.py::test_queue_oldest_first_ageing_and_lease_409 -v` |
| **F17** | Verify decision accepted | Status `PENDING → ACTIVE`, reviewer recorded, accepted values written | `cd backend && uv run pytest tests/inbox/test_verification.py::test_verify_writes_active_with_reviewer -v` |
| **F18** | Reject or correct without a reason | `422`; nothing changes | `cd backend && uv run pytest tests/inbox/test_verification.py::test_correct_and_reject_require_reason -v` |
| **F19** | **Stage 12 never dispatches** | A blocked prescription at the grain is re-evaluated only; a still-failing re-evaluation stays `BLOCKED`; **zero provider calls** | `cd backend && uv run pytest tests/inbox/test_workflow_update.py::test_stage_12_reevaluates_and_never_dispatches -v` |
| **F20** | **no-automated-path-to-ACTIVE** | With no verify call, the record cannot reach `ACTIVE` by any pipeline stage, retry or reprocess | `cd backend && uv run pytest tests/inbox/test_no_auto_active.py::test_no_automated_path_to_active -v` |
| **F21** | **Two-minute filing target** | A high-confidence document yields a usable record within 120 s, or a queue item within 120 s; `tga_inbox_end_to_end_seconds` recorded and the p95 alert fires above 120 s | `cd backend && uv run pytest tests/inbox/test_latency.py::test_inbox_to_chart_under_two_minutes -v` |

## Security

| ID | Case | Expected | Command |
| --- | --- | --- | --- |
| **S1** | **Cross-tenant matching with a canary tenant** | No candidate from the canary tenant; the document routes to manual resolution; `404` on direct access | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_matching_never_crosses_tenant_boundaries -v` |
| **S2** | Canary-tenant message visibility | Not visible in the queue, list or detail; `404`, never `403` | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_cross_tenant_message_not_visible -v` |
| **S3** | Raw SQL as `clinos_app` without a tenant predicate | Only the caller's tenant rows return | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_rls_holds_without_app_filter -v` |
| **S4** | `app.tenant_id` unset | Zero rows, no error (`NULLIF` fails closed) | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_missing_tenant_setting_returns_zero_rows -v` |
| **S5** | Insert with another tenant's `tenant_id` | `WITH CHECK` rejection: `new row violates row-level security policy` | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_with_check_blocks_cross_tenant_insert -v` |
| **S6** | Connection-pool reuse across alternating tenants | No response carries another tenant's data | `cd backend && uv run pytest tests/isolation/test_tga_inbox_isolation.py::test_pool_reuse_no_leak -v` |
| **S7** | **MIME bypass** — declared `application/pdf` with non-PDF magic bytes; declared image with a PDF body | Quarantined, `content_type` taken from magic bytes, **never parsed** | `cd backend && uv run pytest tests/security/test_tga_inbox_validation.py::test_mime_and_magic_byte_mismatch_quarantined -v` |
| **S8** | **Malware bypass** — a client attempts to set `scan_state = 'CLEAN'` directly; an unclean attachment is fetched | Write rejected (column not client-writable / not granted); the object is never served | `cd backend && uv run pytest tests/security/test_tga_inbox_validation.py::test_scan_state_cannot_be_forged_and_unclean_never_served -v` |
| **S9** | **Filename / extension path escape** — `../../etc/passwd`, `a.pdf.exe`, a name used to build a key | Refused or sanitised; no object written outside the tenant prefix; the stored key is server-generated | `cd backend && uv run pytest tests/security/test_tga_inbox_validation.py::test_filename_never_becomes_a_path -v` |
| **S10** | **OCR text as injection** — document text instructs the model to select a patient or emit an approval number | Extraction stays field-scoped and schema-valid; no patient is selected by document text; the injection attempt is logged as a security signal | `cd backend && uv run pytest tests/security/test_tga_inbox_injection.py::test_document_text_cannot_steer_extraction -v` |
| **S11** | **Extractor cannot write an approval** | The extractor role has no `INSERT`/`UPDATE` on `tga_approvals`; a direct attempt raises `42501` | `cd backend && uv run pytest tests/security/test_tga_inbox_grants.py::test_extractor_role_cannot_write_approvals -v` |
| **S12** | **Grant inspection** — `information_schema.role_table_grants` | `tga_extraction_results` has `{SELECT, INSERT}` plus column-level `UPDATE` on the three acceptance columns only; no `DELETE`/`TRUNCATE`; inbox tables have no `UPDATE`/`DELETE` | `cd backend && uv run pytest tests/security/test_tga_inbox_grants.py::test_extraction_accept_only_and_append_only_grants -v` |
| **S13** | `UPDATE tga_extraction_results SET raw_value = …` | `42501 insufficient_privilege`; `raw_value` and `confidence` are immutable | `cd backend && uv run pytest tests/security/test_tga_inbox_grants.py::test_raw_value_and_confidence_immutable -v` |
| **S14** | Role × endpoint matrix | Only authorised roles succeed; refusals are audited; unauthenticated `401`, unpermitted `403` | `cd backend && uv run pytest tests/security/test_tga_inbox_rbac.py::test_role_endpoint_matrix -v` |
| **S15** | Verify or threshold change without fresh step-up | `401 step_up_required`; nothing changes | `cd backend && uv run pytest tests/security/test_tga_inbox_auth.py::test_verify_and_threshold_change_require_step_up -v` |
| **S16** | Reviewer without a care relationship for the patient | `403`; the item does not enter their queue; refusal audited | `cd backend && uv run pytest tests/inbox/test_verification.py::test_reviewer_care_relationship_enforced -v` |
| **S17** | Sentinel OCR text, subject and filename in every sink | Zero occurrences in logs, error bodies, stack traces and telemetry | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_inbox_payloads_contain_no_phi -v` |
| **S18** | Mailbox flood / oversized burst | `429` with `Retry-After`; excess queued or sent to the DLQ; backpressure metric recorded | `cd backend && uv run pytest tests/security/test_tga_inbox_rate_limits.py::test_mailbox_flood_rate_limit_and_dlq -v` |
| **S19** | A stage emits an action name absent from `07` §1 | The audit writer's schema rejects the name; the event-coverage test fails | `cd backend && uv run pytest tests/security/test_audit_action_catalogue.py::test_unregistered_action_name_rejected -v` |
| **S20** | Upload body supplies `tenant_id`, `scan_state`, `patient_id`, `accepted_value` or `state` | `422` unknown field; mass assignment blocked | `cd backend && uv run pytest tests/security/test_tga_inbox_validation.py::test_body_mass_assignment_rejected -v` |

## Audit

| ID | Case | Expected | Command |
| --- | --- | --- | --- |
| **A1** | One document through the full pipeline | One event per stage, each carrying the originating message's `correlation_id` | `cd backend && uv run pytest tests/inbox/test_audit.py::test_stage_events_share_correlation_id -v` |
| **A2** | Forced audit insert failure | The pipeline stops at that stage; no approval written; alert raised | `cd backend && uv run pytest tests/inbox/test_audit.py::test_audit_write_failure_stops_pipeline -v` |
| **A3** | Event payload inspection | No document text, OCR value, subject, filename or patient name in any payload | `cd backend && uv run pytest tests/inbox/test_audit.py::test_audit_carries_no_document_content -v` |
| **A4** | A quarantined message and a refused verification | Both audited with the same fidelity as a success | `cd backend && uv run pytest tests/inbox/test_audit.py::test_denied_and_failed_audited_equally -v` |
| **A5** | Confidence threshold changed | Audited with old value, new value, actor, step-up and reason | `cd backend && uv run pytest tests/inbox/test_audit.py::test_threshold_change_audited -v` |

## Gate evidence mapping

| Gate 5 check | Evidence |
| --- | --- |
| TGA ingestion cannot write a gating state without a human verification | F20, S11, S12 |
| Every provider has a written data-flow record; vendor terms/region recorded | `16` §2 entries for V-04, V-07, V-08 (all open) |
| Webhook/ingest events are deduplicated on the provider identifier | F13, F15 |
| A sandbox integration test passes end to end | F1–F19 in Staging against the sandbox mailbox |
| Credentials are per environment in Secrets Manager with a named owner | S15 plus the credential inventory |

## Traceability

F1–F21 cover R1–R24 in `01-requirements.md`. S1–S20 cover the security criteria in `02-user-stories.md`
and the controls in `04-threat-model.md`, including T-09.1…T-09.18. A1–A5 cover the event catalogue in
`05-data-and-audit.md`. The 2-minute target (R22) is proven by F21 and reviewed monthly with the CSO
alongside the human-verification rate and the correction rate.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| F21 requires a load harness and a Staging mailbox; the throughput profile is unset | Head of Platform | OPEN |
| S10 injection corpus: the document layouts and adversarial fixtures are not yet authored | Security Lead | OPEN |
| S12 grant assertions depend on the `tenant_policy` table (OPEN-2) and provenance columns (OPEN-3) landing | CTO | OPEN |
| Canary-tenant fixtures for the matching test | Security Lead | OPEN |
