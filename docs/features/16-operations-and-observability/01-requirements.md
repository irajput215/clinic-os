---
doc_id: OZ-FEAT-16-REQ
title: "Operations and observability — requirements"
owner: Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-16
phase: 04-phase-4-pilot-go-live
gate: [6, 7]
source:
  - clinic-os-secure-by-design/29-operations-and-observability.md
  - clinic-os-secure-by-design/18-incident-response.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
---

# Operations and observability — requirements

## Purpose
Detect that something is wrong before a clinician reports it, and prove what happened afterwards. This
feature owns the five log categories, the structured log contract and redaction pipeline, the metric and
alert catalogues, secrets management, incident readiness and the backup/restore position.
Source: `29-operations-and-observability.md` "How to take this point"; `21-technical-design.md` §10.

## Requirements and test traceability

| ID | Requirement | Acceptance criterion | Verified by (pytest path) |
|---|---|---|---|
| **R1** | Structured log contract | Every request line is JSON with `request_id, correlation_id, tenant_context, user_context, service, route, method, status, latency_ms, outcome, log_category, app_version, environment`; free-text concatenation is not permitted | `tests/observability/test_log_contract.py::test_every_request_line_has_mandatory_fields` |
| **R2** | Log prohibition | No clinical content, secret or full clinical request body reaches a log line, an analytics pipeline or error telemetry — not in a debug line, stack trace or crash report | `tests/security/test_no_phi_in_log_payload.py::test_sentinel_clinical_value_absent_from_all_sinks` |
| **R3** | Redaction before the sink | Classification lookup, redaction/pseudonymisation and deny-list scrub run before every sink write, with no bypass for debug, trace, crash or error paths | `tests/observability/test_redaction.py::test_pipeline_runs_on_error_paths` |
| **R4** | Five log categories | Application, security, audit, integration and infrastructure logs are **separate stores**, not one stream with a `category` field | `tests/observability/test_log_categories.py::test_five_separate_sinks_configured` |
| **R5** | Tenant-aware log queries | Application and audit queries are tenant-scoped; no cross-tenant log view exists for a clinic role | `tests/observability/test_tenant_scoped_queries.py::test_log_query_returns_only_own_tenant` |
| **R6** | Metric catalogue | Every metric has a unit and a named owner, and the catalogue emits the business signals: API latency p50/p95/p99 by route, error rate, database latency and connection saturation, queue depth and age, worker failure and retry counts, integration failure and latency per provider, webhook lag, notification delivery, prescriptions not in a terminal state, audit write failures, cross-tenant denials | `tests/observability/test_metric_catalogue.py::test_catalogue_signals_are_emitted` |
| **R7** | Bounded metric labels | No metric label carries a patient identifier, a raw actor identifier or a high-cardinality value | `tests/observability/test_metric_catalogue.py::test_labels_are_bounded` |
| **R8** | Trace classification | Trace attributes follow the log classification rules; sampling never captures a request body | `tests/observability/test_traces.py::test_trace_attributes_carry_no_sensitive_value` |
| **R9** | Alert catalogue completeness | Every enabled alert has one threshold, one severity, one route, one runbook and one named owner; an incomplete alert is removed or completed before it is enabled | `tests/observability/test_alerts.py::test_every_enabled_alert_resolves_to_a_runbook_anchor` |
| **R10** | Page on the named conditions | A page fires on cross-tenant authorisation denial spike, prescription non-terminal age beyond threshold, audit write failure, reconciliation job failure, backup or restore failure, and WAF block-rate anomaly | `tests/observability/test_alerts.py::test_named_page_conditions_fire` |
| **R11** | Secrets never persist | No secret in source, image, task definition, build log or ticket; secret scanning runs pre-commit and in CI and a finding blocks the build | `tests/observability/test_secrets.py::test_no_secret_in_source_image_or_build_log` |
| **R12** | Rotation per secret class | Every secret class has a rotation cadence with an overlap window, a named owner, and a Staging test before Production | `tests/observability/test_secrets.py::test_rotation_has_overlap_and_staging_evidence` |
| **R13** | Exposure is an incident | A suspected secret exposure opens an incident under runbook R3, with rotation, a log and image search, and a blast-radius review — never a cleanup task | `tests/observability/test_secrets.py::test_suspected_exposure_opens_incident` |
| **R14** | Severity and response | SEV1–SEV4 are defined with acknowledge and containment targets; a SEV1 with health information is assessed under the Notifiable Data Breaches scheme from suspicion | `tests/observability/test_incident_readiness.py::test_severity_targets_recorded` |
| **R15** | Runbooks name people | Every runbook names a **person**, not a role, with a backup; an unnamed runbook fails the Gate 7 check | `tests/observability/test_incident_readiness.py::test_runbooks_name_people_not_roles` |
| **R16** | Notifiable-breach path | The eligible-data-breach assessment path is documented, owned by the Privacy Officer and understood; the statutory window is marked for validation | `tests/observability/test_incident_readiness.py::test_ndb_assessment_path_is_recorded` |
| **R17** | Audit write failure is loud | A failed audit write fails the operation and alerts immediately | `tests/observability/test_alerts.py::test_audit_write_failure_fails_operation_and_pages` |
| **R18** | Denials fail closed and alert | A missing or invalid tenant context fails closed, and a cross-tenant denial is counted and can trigger a page | `tests/observability/test_alerts.py::test_rls_context_failure_fails_closed_and_alerts` |
| **R19** | Probes leak nothing | Liveness and readiness probes expose no tenant data and no more than a boolean status, and are never routed through tenant resolution | `tests/observability/test_probes.py::test_readiness_probe_exposes_no_tenant_data` |
| **R20** | Backup and restore | Encrypted backups run; a timed restore drill is performed inside the agreed RPO and RTO and re-applies later deletion manifests | `tests/observability/test_restore.py::test_restore_reapplies_deletion_manifests` |
| **R21** | Privileges by grant | The non-owner application role `clinos_app` holds only the grants each store needs; append-only stores take `INSERT, SELECT` and never `UPDATE, DELETE, TRUNCATE` | `tests/security/test_append_only_grants.py::test_observability_grants_are_least_privilege` |
| **R22** | Configuration fails closed | Configuration comes from environment variables or the secret store; a missing required key fails startup rather than defaulting permissive | `tests/observability/test_config.py::test_missing_required_config_fails_startup` |

## Out of scope for this feature
| Item | Why |
|---|---|
| Dashboard product choice and panel build | `29 §7` defines the four dashboards; the tooling choice is OPEN under D-004 |
| SIEM, trace backend and error-monitor products | Vendor position is **REQUIRES LEGAL/REGULATORY VALIDATION** (`29` open item O2) |
| RPO and RTO figures | A business decision for the Practice Owner and CTO (`29 §10`; Gate 6) |
| Cross-region replication for recovery | Disabled by default; residency test and ADR required (`29 §10`; `29` open item O9) |
| Session recording for production access | Capability and privacy position unconfirmed (`29` open item O5) |
| AWS-specific sink configuration | Blocked by [`D-004`](../../reference/decisions/D-004-deployment-target.md) until the deployment target is chosen |

## Open items
| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | Repo-side runbook set does not exist; `gates.md` Gate 7 requires runbooks naming **people, not roles** — this feature states the rule, the runbook artefact is unowned | Head of Platform + Security Lead | OPEN |
| OPEN-2 | The root `.env` is tracked in git and holds `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `POSTGRES_PASSWORD` at template defaults — a live violation of R11; untrack, add `.gitignore`, ship `.env.example`, rotate | Security Lead | OPEN — Phase 0 exit task (D-004 item 3) |
| OPEN-3 | `21 §10` names six page conditions but no severity and no runbook anchor; `29 §5` names severity and R1–R8 for its own alerts | Security Lead | OPEN |
| OPEN-4 | Units exist for every metric, but targets are named by the source only for clinical record p95 (200 ms) and inbox processing (two minutes); every other threshold needs a business figure | Head of Platform | OPEN |
| OPEN-5 | Log retention per category and per jurisdiction | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-6 | Whether any log sink, trace backend, error monitor or SIEM is offshore, and the register row | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-7 | Notifiable-breach notification windows and the multi-tenant who-notifies-whom question | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-8 | Sink selection, region pin and environment-separation evidence are blocked while [`D-004`](../../reference/decisions/D-004-deployment-target.md) is unresolved | CTO + Head of Platform | OPEN — blocks Gate 6 |
| OPEN-9 | On-call rota and alert routes are not assigned to named people with a backup | Head of Platform | OPEN |
