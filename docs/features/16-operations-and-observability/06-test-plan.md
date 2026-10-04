---
doc_id: OZ-FEAT-16-TEST
title: "Operations and observability — test plan"
owner: Security Lead + Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/29-operations-and-observability.md §11
  - clinic-os-secure-by-design/02-security-architecture.md §8
  - clinic-os-secure-by-design/27-security-testing.md §2, §6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
---

# Test plan

All tests run in CI against synthetic data; a failing security test blocks merge. Sentinel values are distinctive and synthetic (`27 §6`). Every row names the exact command that produces the evidence.

## Functional tests

| ID | Case | Expected result | Evidence (exact command) |
|---|---|---|---|
| **F1** | A log line is emitted without `request_id` or `correlation_id` | Dropped and counted, never emitted (envelope validator fails closed) | `cd backend && uv run pytest tests/observability/test_log_contract.py::test_missing_request_id_is_dropped_not_emitted -v` |
| **F2** | Every request log line is inspected | All mandatory fields present; `route` is a template, not a path | `cd backend && uv run pytest tests/observability/test_log_contract.py::test_every_request_line_has_mandatory_fields -v` |
| **F3** | Log configuration is inspected | Five separate sinks exist; no single stream with a `category` field | `cd backend && uv run pytest tests/observability/test_log_categories.py::test_five_separate_sinks_configured -v` |
| **F4** | A request fans out to a queue and a worker | The lines join by `correlation_id` across the synchronous call and the worker | `cd backend && uv run pytest tests/observability/test_correlation.py::test_sqs_fanout_joinable_by_correlation_id -v` |
| **F5** | An outbound provider call is made | It carries `correlation_id`; only the provider reference is stored, never the payload | `cd backend && uv run pytest tests/observability/test_correlation.py::test_outbound_call_carries_correlation_id_without_payload -v` |
| **F6** | The enabled alert set is inspected | Every alert resolves to an existing runbook anchor, a severity and an owner | `cd backend && uv run pytest tests/observability/test_alerts.py::test_every_enabled_alert_resolves_to_a_runbook_anchor -v` |
| **F7** | A restore is followed by the deletion manifests | Records purged before the backup remain purged after the restore | `cd backend && uv run pytest tests/observability/test_restore.py::test_restore_reapplies_deletion_manifests -v` |
| **F8** | A required configuration key is removed | Startup fails rather than defaulting permissive | `cd backend && uv run pytest tests/observability/test_config.py::test_missing_required_config_fails_startup -v` |
| **F9** | The metric catalogue is exercised end to end | The named business signals are emitted | `cd backend && uv run pytest tests/observability/test_metric_catalogue.py::test_catalogue_signals_are_emitted -v` |

## Security tests

| ID | Case | Expected result | Evidence (exact command) |
|---|---|---|---|
| **S1** | A synthetic clinical value is processed through every path | The sentinel appears in **no** log sink, metric label or trace attribute | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_sentinel_clinical_value_absent_from_all_sinks -v` |
| **S2** | A sentinel is planted in a metric label and a trace attribute | Both are rejected or redacted; the value never reaches a backend | `cd backend && uv run pytest tests/observability/test_sentinels.py::test_sentinel_absent_from_metric_labels_and_trace_attributes -v` |
| **S3** | A synthetic token and key value pass the logger | Blocked by the redaction pipeline; `security.redaction.blocked` is raised | `cd backend && uv run pytest tests/observability/test_redaction.py::test_secret_sentinel_blocked_and_alerts -v` |
| **S4** | An inbox message carries a patient name in the subject and filename | No name appears in any sink; only a document reference and content type | `cd backend && uv run pytest tests/observability/test_redaction.py::test_filename_and_subject_absent_from_sinks -v` |
| **S5** | Metric series are enumerated | No series contains a patient identifier, a raw actor identifier or a high-cardinality label | `cd backend && uv run pytest tests/observability/test_metric_catalogue.py::test_labels_are_bounded -v` |
| **S6** | A clinic-scoped log query runs as tenant A | Only tenant A's events are returned | `cd backend && uv run pytest tests/observability/test_tenant_scoped_queries.py::test_log_query_returns_only_own_tenant -v` |
| **S7** | Cross-tenant denials are driven above the threshold | The denial-spike alert fires and reaches the named route | `cd backend && uv run pytest tests/observability/test_alerts.py::test_cross_tenant_denial_spike_pages -v` |
| **S8** | The readiness probe is called with and without tenant context | Boolean status only; no tenant data; never routed through tenant resolution | `cd backend && uv run pytest tests/observability/test_probes.py::test_readiness_probe_exposes_no_tenant_data -v` |
| **S9** | A module contains a silent catch or a default-allow branch | The test/lint fails; the error path emits a distinguishable log and metric | `cd backend && uv run pytest tests/security/test_errors_fail_closed.py::test_no_silent_catch -v` |
| **S10** | The image and repository are scanned | No secret in source, image layer, build log or ticket | `cd backend && uv run pytest tests/observability/test_secrets.py::test_no_secret_in_source_image_or_build_log -v` |
| **S11** | `information_schema.role_table_grants` is inspected for `clinos_app` | The audit store holds `{SELECT, INSERT}` only; no `UPDATE`, `DELETE` or `TRUNCATE` | `cd backend && uv run pytest tests/security/test_append_only_grants.py::test_observability_grants_are_least_privilege -v` |

## Audit and alerting tests

| ID | Case | Expected result | Evidence (exact command) |
|---|---|---|---|
| **A1** | An audit write failure is induced on an audited operation | The operation fails closed and the alert reaches the on-call route | `cd backend && uv run pytest tests/observability/test_alerts.py::test_audit_write_failure_fails_operation_and_pages -v` |
| **A2** | A request arrives with a missing or invalid tenant context | It fails closed, returns zero rows and raises the RLS-context alert | `cd backend && uv run pytest tests/observability/test_alerts.py::test_rls_context_failure_fails_closed_and_alerts -v` |
| **A3** | A prescription is held in a non-terminal state beyond the threshold | The non-terminal-age alert fires for the Clinical Safety Officer route | `cd backend && uv run pytest tests/observability/test_alerts.py::test_non_terminal_prescription_age_pages -v` |
| **A4** | The observability event catalogue is emitted after the five names are added to `07 §1` | `incident.opened`, `incident.resolved`, `alert.fired` and `break_glass.used` each produce one event with the full envelope | `cd backend && uv run pytest tests/observability/test_audit_events.py::test_observability_event_catalogue_emitted -v` |

## CI hooks and observability list

The silent-catch coverage is enforced in two places: the pytest case `S9` above, and the lint stage with `ruff` rules `S110` (try-except-pass) and `BLE001` (blind except) added to the selected set in `backend/pyproject.toml`, run as `cd backend && uv run ruff check app`. This maps `O1–O14` in `29 §11` to the rows above: `O1–O4` to `S1–S3`, `O5` to `F1`, `O6–O7` to `F4–F5`, `O8` to `S6`, `O9–O10` to `A1–A2`, `O11` to `S4`, `O12` to `S5`, `O13` to `F6`, `O14` to `F7`.

## Traceability

`F1–F9` cover `R1`, `R4`, `R5`, `R6`, `R9`, `R20` and `R22`. `S1–S11` cover `R2`, `R3`, `R7`, `R8`, `R10`, `R11`, `R13`, `R18`, `R19` and `R21`, and the controls in [04-threat-model.md](04-threat-model.md). `A1–A4` cover `R14`, `R16`, `R17` and the event catalogue in [05-data-and-audit.md](05-data-and-audit.md). `R12` (rotation evidence) and `R15` (runbooks naming people) cannot be fully evidenced until the named-person runbook and rotation records exist; both are open items blocking Done.
