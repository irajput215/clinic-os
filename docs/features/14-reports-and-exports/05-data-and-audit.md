---
doc_id: OZ-FEAT-14-DATA
title: "Reports and exports — data classification, residency and audit"
owner: Compliance Lead + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §4, §5
  - clinic-os-secure-by-design/13-data-residency.md §1, §4
  - clinic-os-secure-by-design/14-retention-and-deletion.md §2, §3, §4
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2
  - clinic-os-secure-by-design/08-tga-approval-model.md §6
  - Privacy Act 1988 (Cth) APP 11.2, APP 12, APP 13
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data, residency and audit

## Field classification

Levels are the **seven** from `12 §1`: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`,
`HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. The last column applies the `12 §4` decision table
to the exported field: may it appear in an application log, an audit event, analytics.

| Field | Level | In log | In audit | In analytics | `12 §4` permits |
| --- | --- | --- | --- | --- | --- |
| `id`, `tenant_id`, `row_count`, `status` | INTERNAL | yes | yes | yes | yes in all columns |
| `reason_code`, `failure_code`, `state`, `version` | SENSITIVE | yes, pseudonymous actor | yes | aggregate only | log yes; audit yes; analytics aggregate only |
| `filter`, `parameters`, `scope_note` | SENSITIVE | **no** | action only | never | free text is excluded from logs and analytics (`12 §5.4`) |
| `reason_note`, `refusal_reason`, `decision_ground_code` | SENSITIVE | **no** | yes | never | captured in audit where a legal process needs it, never logged |
| `requested_by`, `handled_by`, `approved_by`, `prescriber_id` | SENSITIVE | pseudonymous | yes | never | pseudonymised only |
| `subject_patient_id`, `patient_id` | HEALTH_INFORMATION | pseudonymised | yes, identifiers permitted | pseudonymous, minimum cohort | never raw in a log |
| Approval categories and dosage forms inside a report | HIGHLY_SENSITIVE | **never** | action recorded, content never | aggregate count only | never in a log, an analytics pipeline or error telemetry |
| Patient-level export rows | HIGHLY_SENSITIVE | **never** | action only | never | export is gated, watermarked and audited |
| Artefact object bytes | HIGHLY_SENSITIVE | never | action only | never | private bucket, presigned URL only |
| `artefact_object_key` | CONFIDENTIAL | never in full | yes | never | access path; never logged whole |
| Presigned URL and its signature | SECRET | never | never | never | never in any column, log or export |
| `artefact_sha256` | SENSITIVE | no | yes | never | integrity evidence |

`HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not in a debug
line, not in a stack trace, not in a crash report (`12 §2`).

## Residency

All fields are stored and processed in `ap-southeast-2`. The exports bucket is region-pinned and its
policy denies a request unless `aws:RequestedRegion` is `ap-southeast-2` (`13 §4`). An export that
leaves the platform is a cross-border flow, not merely a download: any future recipient must satisfy
all five conditions of `13 §1` and be registered before any production health information is sent.
Today no such integration exists — **REQUIRES LEGAL/REGULATORY VALIDATION** with the Compliance Lead.

## Audit event catalogue

| Event | Trigger | Key fields beyond the envelope |
| --- | --- | --- |
| `export.requested` | A `export_jobs` row is created | `export_job_id`, `scope`, `reason_code`, `row_count` (null at request), `step_up` |
| `export.downloaded` | A presigned URL is minted, and again when the object is fetched where observable | `export_job_id`, `actor_id`, `purpose`, `ttl_seconds` |
| `export.expired` | The expiry job deletes the artefact | `export_job_id`, `row_count`, `age_seconds` |
| `report.generated` | A `report_runs` row reaches `succeeded` | `report_run_id`, `template_code`, `period_start`, `period_end`, `version`, `row_count` |
| `retention.job_run` | A purge run completes or aborts | `job_id`, `schedule_version`, `rule_id`, `jurisdiction`, `candidates`, `purged`, `held`, `failed` |
| `dsar.received` | A request reaches any channel | `request_id`, `request_type`, `clock_started_at` |
| `dsar.fulfilled` | The response is issued and the evidence stored | `request_id`, `decision`, `fulfilment_export_job_id` |
| `export.denied`, `report.denied`, `dsar.denied` | Any refused attempt | `attempted_action`, `denial_reason` (permission, tenant, step_up, reason_code, scope) |

**Registration required before use.** None of the names above appears in
`07-audit-architecture.md` §1, which is the authoritative action vocabulary, and `07 §1` states that no
module invents an action name outside that table without adding it there first. The nearest registered
names are `patient.export` (`07 §1`), which covers a patient export but carries no reporting or DSAR
meaning, and the SCREAMING_SNAKE names `EXPORT_REQUESTED`, `EXPORT_DOWNLOADED`, `REPORT_RUN` in
`20 §9`, which are a different vocabulary again. The eight names above are therefore **proposed, not
approved**; each must be registered in `07 §1` with a resource type before it is emitted. `EXPORT` and
`REPORT` already exist in the envelope `resource_type` enum (`07 §2`), so no new resource type is
needed for those two; a DSAR or retention resource type would be new — OPEN-5.

## Standard envelope

Every event carries the envelope from `07 §2` unchanged: `event_id`, `timestamp` (UTC, server clock),
`tenant_id` (from context, never the body), `actor_id` (or `SYSTEM` with the job name in `reason`),
`actor_role` at decision time, `action`, `resource_type`, `resource_id`, `result` in
`{SUCCESS, DENIED, FAILED, UNKNOWN}`, `reason` as a controlled code, `source_ip`, `request_id`,
`correlation_id`, `prev_hash`, `hash`. No clinical payload. **Denied and failed attempts are audited
with the same fidelity as successes**, and a failed audit write fails the action closed.

## Retention and deletion

Minimum retention, from `14 §2`:

| Record set | Minimum retention | Deletion mode |
| --- | --- | --- |
| Patient records and demographics | **At least 7 years from the last clinical service** for adults; **until age 25** for a minor under NSW s 25 and Victoria HPP 4.2 | soft delete then scheduled purge |
| Data access and correction (DSAR) records | **7 years** as a complaints and evidence record | archive then purge |
| TGA approvals | Approval validity plus the clinical record retention period; validity is 2 years at the grain | archive then purge |
| Audit logs | 12 months recommended, longer where the log forms part of the clinical record | archive, then never delete inside the window |
| Export artefacts and temporary files | Shortest period the processing needs; 30 days recommended as an outer bound | hard delete at expiry |

**Hard deletes of clinical and DSAR records are disallowed.** `14 §3.1` permits only soft delete plus a
scheduled purge for patients, clinical records, notes, prescriptions and TGA approvals; the app role
holds no `DELETE` on the tables in `03-design.md`. An artefact is the exception: it is a temporary
processing copy, so it is hard-deleted at `expires_at`. A legal hold suspends purge, excludes the
record from candidate selection and counts the exclusion (`14 §3.6`, §3.2).

Per-jurisdiction periods, the operator for a patient who moves between jurisdictions, and every
period beyond NSW and Victoria remain **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy
Officer (`14 §2`; `17-compliance-control-matrix.md` STATE-01, L2).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Registration of the eight audit action names in `07 §1`, and the DSAR/retention resource types (OPEN-5) | Security Lead | OPEN |
| Whether the audit-log retention of 12 months recommended satisfies NDB reconstruction for this module | Security Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Retention period of `report_runs` and `export_jobs` rows themselves (OPEN-4) | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| The exact reporting fields and format; `08 §6` names none (OPEN-1) | Compliance Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
