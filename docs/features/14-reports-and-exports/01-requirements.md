---
doc_id: OZ-FEAT-14-REQ
title: "Reports and exports — requirements"
owner: Compliance Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/14-retention-and-deletion.md §2, §3, §4
  - clinic-os-secure-by-design/08-tga-approval-model.md §6
  - clinic-os-secure-by-design/12-data-classification.md §1, §4
  - clinic-os-secure-by-design/05-tenant-isolation.md §8
  - clinic-os-secure-by-design/26-security-gates.md §5
  - clinic-os-secure-by-design/02-security-architecture.md §11
  - clinic-os-secure-by-design/17-compliance-control-matrix.md TGA-03, APP-13, STATE-01
  - clinic-os-secure-by-design/20-product-requirements.md §9
  - clinic-os-secure-by-design/22-user-stories.md US-28
repo_docs:
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Reports and exports: requirements

## Purpose

Assemble the reports a prescriber and a clinic need, and control bulk export of patient-level data so
that a legitimate access or regulatory request can be met while bulk access stays visible and bounded.

The reporting workspace is a **drafting aid**. The prescriber reviews and submits; the platform does
not submit on the prescriber's behalf, because no documented integration exists (`08 §6`).

## Requirements and test traceability

| ID | Requirement | Acceptance criteria | Verified by |
|---|---|---|---|
| **R1** | Report generation is privileged | A caller without `reports:export` receives `403` and an audited denial; no `report_runs` row is written | `tests/reports/test_report_run.py::test_report_run_requires_permission` |
| **R2** | Aggregate reports carry no patient-level rows | Report output contains counts only; zero patient identifiers in the artefact (`20 §9`) | `tests/reports/test_report_run.py::test_report_aggregate_contains_no_patient_identifiers` |
| **R3** | A bulk export requires a typed reason | Request without `reason_code` from the controlled list returns `422 ERR_EXPORT_REASON_REQUIRED`; zero `export_jobs` rows | `tests/exports/test_export_request.py::test_export_without_reason_refused` |
| **R4** | A bulk export requires step-up | No step-up within the window returns `401 step_up_required`; nothing generated (`06 §9` `patient:export`) | `tests/exports/test_export_request.py::test_export_without_step_up_refused` |
| **R5** | Export generation is asynchronous | `POST` returns `202` with a job id; no artefact is produced inside the request | `tests/exports/test_export_request.py::test_export_returns_202_and_generates_async` |
| **R6** | Download re-authorises the requester | Minting a URL re-checks permission, tenant and the requester's live authority; a revoked requester gets `403`, no file served (`05 §8` I-028) | `tests/exports/test_export_download.py::test_download_reauthorises_requester` |
| **R7** | The presigned URL is short-lived and identity-bound | TTL exactly 300 s server-side; bound to the exact object key; a URL presented by another identity is refused | `tests/exports/test_export_download.py::test_presigned_url_ttl_and_identity_binding` |
| **R8** | Bulk exports are watermarked | Artefact carries tenant, requester, purpose code and generation timestamp on every page or record batch | `tests/exports/test_export_artefact.py::test_bulk_export_is_watermarked` |
| **R9** | Artefacts expire and are deleted on schedule | After expiry the object is deleted, the job is `expired`, and a new download is refused | `tests/exports/test_export_expiry.py::test_artefact_expiry_deletes_object` |
| **R10** | Export is rate-limited per session and tenant, plus a daily quota | 6th request in an hour returns `429`; exceeding the per-tenant daily quota returns `429`; every request alerts (`02 §11`) | `tests/exports/test_export_rate_limits.py::test_export_five_per_hour_and_daily_quota` |
| **R11** | An export cannot cross a tenant | An export run as tenant A over a filter matching tenant B rows contains only A's rows, count asserted exactly (`05 §8` I-027) | `tests/isolation/test_export_isolation.py::test_export_job_tenant_scoped` |
| **R12** | Cross-tenant report and export access returns `404` | Tenant A requesting B's `report_run` or `export_job` id gets `404`, never `403` | `tests/isolation/test_export_isolation.py::test_cross_tenant_report_and_export_return_404` |
| **R13** | The application role holds no delete privilege | `information_schema.role_table_grants` shows no `DELETE` or `TRUNCATE` for `clinos_app` on report, export, DSAR and retention tables | `tests/security/test_reports_grants.py::test_app_role_holds_no_delete_on_reports_tables` |
| **R14** | A correction request never performs a hard delete | An APP 13 request appends a correction or archives; the original is not overwritten and no row is physically removed (`14 §3.5`) | `tests/reports/test_dsar.py::test_correction_appends_never_hard_deletes` |
| **R15** | A deletion request is an assessment, not an action | A request on a record inside retention produces a recorded refusal with a reason (`14 §1`, `14 §5` T13) | `tests/reports/test_dsar.py::test_deletion_request_inside_retention_refused_with_reason` |
| **R16** | A retention job over-deletes nothing | A record inside minimum retention is never selected; a held record is excluded and the exclusion counted (`14 §2`, `14 §3.2`) | `tests/reports/test_retention_job.py::test_purge_never_selects_record_inside_retention` |
| **R17** | The retention job fails closed on legal hold | If the hold check cannot be evaluated the run aborts and purges nothing (`14 §3.2`, T15) | `tests/reports/test_retention_job.py::test_hold_check_failure_aborts_run` |
| **R18** | RLS is enabled and forced on every tenant table here | Cross-tenant insert rejected; no tenant setting returns zero rows | `tests/isolation/test_export_isolation.py::test_rls_forced_on_report_and_export_tables` |

## Out of scope for the MVP

- Submission of the report to any regulator: no integration exists (`08 §6`).
- Report scheduling and delivery by email; `report:schedule` is not evidenced here — OPEN-1.
- Aggregate analytics pipelines not built for a stated report.
- Feature 04's audit-trail export (`/api/v1/audit/export`), which stays owned by that feature.

## Open items

| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | Exact reporting cycle, fields, format and channel — doc 08 §6 calls six-monthly "the working assumption" and names no months | Compliance Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-2 | Whether the artefact TTL is 300 s (doc 07 §243 precedent) or a longer export-specific value | Security Lead | OPEN |
| OPEN-3 | The per-tenant daily quota value; doc 02 §11 requires one and states no number | Head of Platform | OPEN |
| OPEN-4 | Operative retention period per jurisdiction and for a patient who moves | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-5 | The six audit action names below are not in doc 07 §1 and must be registered before use | Security Lead | OPEN |
| OPEN-6 | Whether a missed reporting period must block prescribing; doc 08 §6 says it must not for the MVP | Clinical Safety Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
