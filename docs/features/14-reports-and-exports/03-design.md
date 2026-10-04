---
doc_id: OZ-FEAT-14-DESIGN
title: "Reports and exports — design"
owner: Compliance Lead
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-14
phase: 02-phase-2-tga-approval-engine
gate: [4]
source:
  - clinic-os-secure-by-design/20-product-requirements.md §9
  - clinic-os-secure-by-design/14-retention-and-deletion.md §2, §3, §4
  - clinic-os-secure-by-design/21-technical-design.md §5, §7
  - clinic-os-secure-by-design/05-tenant-isolation.md §5, §8
  - clinic-os-secure-by-design/02-security-architecture.md §11
  - clinic-os-secure-by-design/08-tga-approval-model.md §6
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Table: `report_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | server-generated |
| `tenant_id` | uuid NOT NULL | from session; RLS key |
| `template_code` | text NOT NULL | `CHECK` against a controlled list |
| `period_start`, `period_end` | date NOT NULL | `CHECK (period_end >= period_start)` |
| `prescriber_id` | uuid NULL | FK `users`; required by the prescriber template |
| `parameters` | jsonb NOT NULL DEFAULT '{}' | no free text; strict schema, unknown keys rejected |
| `status` | text NOT NULL | `CHECK IN ('queued','running','succeeded','failed','expired')` |
| `version` | int NOT NULL DEFAULT 1 | `UNIQUE (tenant_id, template_code, period_start, period_end, version)` |
| `supersedes_report_run_id` | uuid NULL | immutability rule (`08 §6`) |
| `row_count` | int NULL | reconciliation evidence |
| `artefact_object_key`, `artefact_sha256` | text NULL | tenant-scoped S3 key; integrity |
| `watermarked` | boolean NOT NULL DEFAULT false | bulk output only |
| `created_by`, `created_at`, `completed_at`, `failure_code` | uuid / timestamptz / text | controlled failure code, never a stack trace |

Indexes: `(tenant_id, template_code, created_at DESC)`, `(tenant_id, status)`.

## Table: `export_jobs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | server-generated |
| `tenant_id` | uuid NOT NULL | from session; RLS key |
| `requested_by`, `requested_session_id` | uuid / text NOT NULL | identity the URL is bound to; binds the artefact to the requesting session |
| `reason_code` | text **NOT NULL** | typed list; `CHECK (reason_code <> '')` (R3) |
| `reason_note` | text NULL | free text; SENSITIVE, never logged |
| `export_scope`, `patient_id` | text NOT NULL / uuid NULL | `CHECK IN ('aggregate','patient_level')`; `patient_id` required for a DSAR-scoped export |
| `filter` | jsonb NOT NULL DEFAULT '{}' | strict schema; no `tenant_id` accepted |
| `status` | text NOT NULL | `CHECK IN ('queued','running','ready','downloaded','expired','failed')` |
| `step_up_ref` | text NOT NULL | step-up assertion id consumed by this request |
| `row_count` | int NULL | |
| `artefact_object_key`, `artefact_sha256` | text NULL | never client-supplied; integrity |
| `watermarked` | boolean NOT NULL DEFAULT false | true for every bulk export |
| `expires_at` | timestamptz NOT NULL | set at readiness; drives R9 |
| `downloaded_at`, `deleted_at`, `failure_code` | timestamptz / text NULL | |

Indexes: `(tenant_id, created_at DESC)`, `(tenant_id, status, expires_at)`,
partial `(expires_at) WHERE status = 'ready'`.

`data_subject_requests`: `id` uuid PK, `tenant_id` uuid NOT NULL, `subject_patient_id` uuid NOT NULL,
`request_type` text `CHECK IN ('access','correction','deletion')`, `state` text `CHECK IN` the nine
states of `14 §4`, `identity_verified_at`, `scope_note`, `decision`, `decision_ground_code`,
`refusal_reason`, `fulfilment_export_job_id` uuid FK, `clock_started_at`, `closed_at`, `handled_by`.
Index `(tenant_id, state, clock_started_at)`.

`retention_jobs`: `id` uuid PK, `tenant_id` uuid NOT NULL, `schedule_version`, `rule_id`,
`jurisdiction` text NOT NULL, `approved_by` uuid NOT NULL, `status` text
`CHECK IN ('running','completed','aborted')`, `candidates`, `purged`, `held`, `failed` int NOT NULL
DEFAULT 0, `oldest_due_unpurged_days` int NULL, `certificate_id` uuid NULL, `started_at`,
`completed_at`. Index `(tenant_id, started_at DESC)`.

## The export contract

| # | Rule | Source |
| --- | --- | --- |
| 1 | Privileged permission: `reports:export`, and `export:bulk` for patient-level scope | `06 §9`; `20 §9` |
| 2 | A **typed reason** is mandatory; the request is refused without it | `02 §11`; `20 §9` |
| 3 | **Step-up** is required before the job is accepted | `22 §US-28`; `06 §9` |
| 4 | Generation is **asynchronous** — `202` plus a job id, never an artefact in the response | `02 §11` |
| 5 | **Re-authorisation at download**: permission, tenant and live authority are recomputed | `05 §8` I-028 |
| 6 | Short-lived **presigned URL bound to the requesting identity**, TTL 300 s, exact key | `21 §5`, `21 §7`; `07 §243` precedent |
| 7 | **Watermark** on bulk exports: tenant, requester, purpose code, timestamp | `12 §2`; `20 §9` |
| 8 | Scheduled **expiry and deletion** of the artefact, with the job closed as `expired` | `20 §9` |
| 9 | A **per-tenant daily quota** in addition to 5 requests per hour | `02 §11` |

The step-up window follows `06 §9`; whether 300 s is the right export TTL is OPEN-2.

## A correction request never hard-deletes

| Input | What the platform does |
| --- | --- |
| APP 12 access | Assembled as a watermarked, expiring export scoped to one patient (APP 12; `14 §4`) |
| APP 13 correction | An **audited correction** is appended and associated; the original is not overwritten (APP 13; `14 §3.5`) |
| Deletion, inside or past retention | **Assessment**: inside retention a recorded refusal with a reason and nothing purged; past retention the request only feeds candidate selection, and the **retention job** purges under legal-hold check (`14 §1`, §3.2, §5 T13) |
| Deletion of audit records | Refused; the refusal and its reason are recorded (`14 §3.5`) |

No DSAR path issues `DELETE`; the app role holds no `DELETE` on any table here (R13), so the rule is
enforced by grant as well as by code.

## RLS and database privileges

- `ENABLE` and `FORCE ROW LEVEL SECURITY` on `report_runs`, `export_jobs`, `data_subject_requests`
  and `retention_jobs` (R18), so an export cannot cross a tenant between job creation and download.
- Policy declared `AS RESTRICTIVE`, `USING` and `WITH CHECK`:
  `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`.
  An unset tenant matches nothing instead of raising a cast error. `SET LOCAL` inside each
  transaction, never on a pooled connection. The app role is not the table owner and holds no
  `BYPASSRLS`.
- No artefact table: artefacts live in the private S3 bucket under `tenants/{tenant_id}/exports/...`
  and are reachable only by presigned URL (`21 §5`).

```sql
GRANT SELECT, INSERT, UPDATE ON report_runs, export_jobs, data_subject_requests, retention_jobs TO clinos_app;
REVOKE DELETE, TRUNCATE ON report_runs, export_jobs, data_subject_requests, retention_jobs FROM clinos_app;
-- clinos_retention may delete only the clinical tables 04-database-erd.md §6 permits, and only
-- through an approved job that checked legal hold first; it may never delete the audit table (14 §3.2)
GRANT SELECT, UPDATE, DELETE ON retention_jobs TO clinos_retention;
REVOKE DELETE, TRUNCATE ON audit_log FROM clinos_retention;
```

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/v1/reports` | `reports:export` | list of run history, cursor-paginated |
| `POST /api/v1/reports/runs` | `reports:export` | `202`; body carries template code and period |
| `GET /api/v1/reports/runs/{id}` | `reports:export` | `404` on cross-tenant |
| `GET /api/v1/reports/runs/{id}/download` | `reports:export` | re-authorised; 300 s URL; watermarked artefact |
| `POST /api/v1/exports` | `reports:export` | `202`; step-up, typed reason, async job |
| `GET /api/v1/exports/{id}` | `reports:export` | `404` on cross-tenant |
| `GET /api/v1/exports/{id}/download` | `reports:export` | re-authorised; identity-bound URL; audit `export.downloaded` |
| `POST /api/v1/data-subject-requests`, `GET /api/v1/data-subject-requests/{id}` | `dsar:manage` | receives an APP 12/13 request; `404` on cross-patient or cross-tenant; permission is OPEN-5 |
| `POST /api/v1/data-subject-requests/{id}/decision` | `dsar:manage` | appends a correction or records a refusal; never deletes |
| `POST /api/v1/retention/jobs` | `retention:run` | system or Privacy Officer; writes `retention.job_run`; permission is OPEN-5 |

## Deny-by-default request path

1. Authenticate the session (deny if missing or expired).
2. Resolve the tenant from the session; `SET LOCAL` it in the transaction.
3. Check the permission for the role (deny if not granted).
4. For a bulk export, verify the step-up assertion and consume it.
5. Audit the decision, including every refusal.
6. Validate the body against a strict schema; `tenant_id` and `object_key` in the body are rejected.
7. Execute inside the RLS-scoped transaction.
8. For a download, re-authorise, then mint the identity-bound URL.

## Failure behaviour

Any error resolving tenant or authorisation denies. A failure in the export worker leaves the job in a
non-terminal state with a `failure_code`, never as success or failure of the underlying data. Errors
return the standard envelope with a request id and no patient data. A download URL is never reused,
cached or emailed.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Artefact TTL for exports (OPEN-2) | Security Lead | OPEN |
| Per-tenant daily quota value (OPEN-3) | Head of Platform | OPEN |
| `dsar:manage` and `retention:run` are not in the `06 §9` permission matrix (OPEN-5) | CTO | OPEN |
| Watermark algorithm: visible overlay against per-record HMAC (OPEN-6) | Security Lead | OPEN |
| The `clinos_retention` delete scope must match `04-database-erd.md` §6 exactly (OPEN-9) | Privacy Officer | OPEN |

