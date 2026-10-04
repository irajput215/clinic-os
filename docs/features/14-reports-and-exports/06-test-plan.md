---
doc_id: OZ-FEAT-14-TEST
title: "Reports and exports — test plan"
owner: Compliance Lead + Security Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/05-tenant-isolation.md §8
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3.2, §5
  - clinic-os-secure-by-design/02-security-architecture.md §11
  - clinic-os-secure-by-design/26-security-gates.md §5
  - clinic-os-secure-by-design/27-security-testing.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 07-definition-of-done.md
---

# Test plan

All tests run in CI on synthetic data with a two-tenant canary fixture. A failing security test blocks
merge. Every row below carries its exact command.

## Functional

| ID | Case | Expected result | Command |
|---|---|---|---|
| **F1** | Run the report template for a period | `202`, then `succeeded`; `row_count` reconciles to the approval register | `cd backend && uv run pytest tests/reports/test_report_run.py::test_report_run_reconciles_to_approval_register -v` |
| **F2** | Aggregate report payload | Zero patient identifiers in the artefact | `cd backend && uv run pytest tests/reports/test_report_run.py::test_report_aggregate_contains_no_patient_identifiers -v` |
| **F3** | Re-run the same period | New `version`; prior run untouched | `cd backend && uv run pytest tests/reports/test_report_run.py::test_report_version_supersedes_and_is_immutable -v` |
| **F4** | Request a bulk export with a typed reason | `202` with a job id; no artefact in the response | `cd backend && uv run pytest tests/exports/test_export_request.py::test_export_returns_202_and_generates_async -v` |
| **F5** | Download a ready export | Presigned URL, watermarked artefact, `export.downloaded` | `cd backend && uv run pytest tests/exports/test_export_download.py::test_download_returns_watermarked_artefact -v` |
| **F6** | Let the artefact reach `expires_at` | Object deleted, job `expired`, further download refused | `cd backend && uv run pytest tests/exports/test_export_expiry.py::test_artefact_expiry_deletes_object -v` |
| **F7** | APP 12 access request for one patient | Bounded export, watermarked, expiring | `cd backend && uv run pytest tests/reports/test_dsar.py::test_access_request_produces_bounded_export -v` |
| **F8** | APP 13 correction request | Correction appended and associated; original intact | `cd backend && uv run pytest tests/reports/test_dsar.py::test_correction_appends_never_hard_deletes -v` |
| **F9** | Deletion request inside minimum retention | Recorded refusal with a ground; nothing purged | `cd backend && uv run pytest tests/reports/test_dsar.py::test_deletion_request_inside_retention_refused_with_reason -v` |
| **F10** | Purge run over a mixed candidate set | Only records past minimum retention selected | `cd backend && uv run pytest tests/reports/test_retention_job.py::test_purge_never_selects_record_inside_retention -v` |

## Security

| ID | Case | Expected result | Command |
|---|---|---|---|
| **S1** | Tenant A requests tenant B's `export_job` id | **`404`**, no body fields, audit `DENIED` | `cd backend && uv run pytest tests/isolation/test_export_isolation.py::test_cross_tenant_export_returns_404 -v` |
| **S2** | Tenant A requests tenant B's `report_run` id | **`404`**, never `403` | `cd backend && uv run pytest tests/isolation/test_export_isolation.py::test_cross_tenant_report_returns_404 -v` |
| **S3** | Export job as A while B rows match the filter | Only A's rows; row count asserted exactly | `cd backend && uv run pytest tests/isolation/test_export_isolation.py::test_export_job_tenant_scoped -v` |
| **S4** | Report run as A with B rows in range | B's rows absent; count assertion names what is absent | `cd backend && uv run pytest tests/isolation/test_export_isolation.py::test_report_run_tenant_scoped -v` |
| **S5** | RLS forced on the four tables; no tenant setting | Zero rows, no error; cross-tenant insert rejected | `cd backend && uv run pytest tests/isolation/test_export_isolation.py::test_rls_forced_on_report_and_export_tables -v` |
| **S6** | `POST /exports` with no `reason_code` | `422 ERR_EXPORT_REASON_REQUIRED`; zero rows | `cd backend && uv run pytest tests/exports/test_export_request.py::test_export_without_reason_refused -v` |
| **S7** | `POST /exports` with no step-up in window | `401 step_up_required`; nothing generated | `cd backend && uv run pytest tests/exports/test_export_request.py::test_export_without_step_up_refused -v` |
| **S8** | Body carries `tenant_id` or `object_key` | `422` unknown field; mass assignment blocked | `cd backend && uv run pytest tests/exports/test_export_request.py::test_export_body_mass_assignment_rejected -v` |
| **S9** | URL TTL and identity binding | `X-Amz-Expires=300`; a URL presented by another identity is refused | `cd backend && uv run pytest tests/exports/test_export_download.py::test_presigned_url_ttl_and_identity_binding -v` |
| **S10** | Revoke the requester's membership, then download | `403`, no file served (re-authorisation at download) | `cd backend && uv run pytest tests/exports/test_export_download.py::test_download_reauthorises_requester -v` |
| **S11** | 6th export request in an hour | `429`; every request alerted | `cd backend && uv run pytest tests/exports/test_export_rate_limits.py::test_export_five_per_hour_and_daily_quota -v` |
| **S12** | Per-tenant daily quota exceeded | `429`, keyed on tenant as well as session | `cd backend && uv run pytest tests/exports/test_export_rate_limits.py::test_export_daily_quota_per_tenant -v` |
| **S13** | Inspect `information_schema.role_table_grants` for `clinos_app` | No `DELETE` and no `TRUNCATE` on `report_runs`, `export_jobs`, `data_subject_requests`, `retention_jobs` | `cd backend && uv run pytest tests/security/test_reports_grants.py::test_app_role_holds_no_delete_on_reports_tables -v` |
| **S14** | App role attempts `DELETE` on `export_jobs` and on `data_subject_requests` | `42501 insufficient_privilege` for both | `cd backend && uv run pytest tests/security/test_reports_grants.py::test_app_role_delete_denied -v` |
| **S15** | DSAR naming another patient's record | `404`; audited as denied; no export created | `cd backend && uv run pytest tests/reports/test_dsar.py::test_dsar_cannot_reach_another_patient_record -v` |
| **S16** | Legal hold on a candidate record | Record excluded, exclusion counted, run completes | `cd backend && uv run pytest tests/reports/test_retention_job.py::test_legal_hold_blocks_purge -v` |
| **S17** | Hold check cannot be evaluated | Run aborts, purges nothing, alert emitted (T15 fail-closed) | `cd backend && uv run pytest tests/reports/test_retention_job.py::test_hold_check_failure_aborts_run -v` |
| **S18** | Purge run for tenant A only | Never deletes tenant B rows (T14) | `cd backend && uv run pytest tests/reports/test_retention_job.py::test_purge_run_never_touches_other_tenant -v` |
| **S19** | Bulk export artefact inspection | Watermark carries tenant, requester, purpose code and timestamp | `cd backend && uv run pytest tests/exports/test_export_artefact.py::test_bulk_export_is_watermarked -v` |
| **S20** | Response and log payload inspection | Zero `HIGHLY_SENSITIVE` value in logs, errors or stack traces | `cd backend && uv run pytest tests/security/test_no_phi_in_log_payload.py::test_export_payloads_contain_no_phi -v` |

## Audit

| ID | Case | Expected |
|---|---|---|
| **A1** | Each successful request, generation or download | One matching event with the full `07 §2` envelope |
| **A2** | Each refusal (permission, tenant, step-up, reason code, scope) | `*.denied` with a machine-readable denial reason |
| **A3** | Audit write fails | The action does not complete (fail closed), alert raised |
| **A4** | `retention.job_run` payload | Carries `schedule_version`, `rule_id`, approver and counts; **no deleted values** (`14 §3.3`) |

## Execution

```bash
# Reports, exports, DSAR and retention
cd backend && uv run pytest tests/reports tests/exports -v
# Tenant isolation for report and export surfaces
cd backend && uv run pytest tests/isolation/test_export_isolation.py -v
# Grants and no-PHI checks
cd backend && uv run pytest tests/security/test_reports_grants.py tests/security/test_no_phi_in_log_payload.py -v
```

## Traceability

F1–F10 cover R1–R9, R14–R17. S1–S20 cover R10–R13, R18 and the controls in `04-threat-model.md`
(T-14.1 S6/S7/S11/S12/S19; T-14.2 S3/S4/S5; T-14.3 S9/S10; T-14.4 S6; T-14.5 S16/S17/S18;
T-14.6 S15; T-14.7 S11/S12; T-14.8 S19; T-14.9 S13/S14; T-14.10 F3). A1–A4 cover the event catalogue
in `05-data-and-audit.md`.

**Test-area naming.** The paths above use `tests/reports/`, `tests/exports/` and
`tests/isolation/test_export_isolation.py`. `05 §8` names the cases `export.job_tenant_scoped`,
`export.download_reauthorises` and `audit.cross_tenant_export_denied` without fixing a file path, and
no `tests/reports/` directory exists in this repo today. The paths must be confirmed against the repo
layout at build time — OPEN (Head of Platform).
