---
doc_id: FEAT-PAT-05
title: Patients, data and audit
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Data and audit

## The seven classification levels
From `12-data-classification.md` §1, which defines **seven**: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`,
`SENSITIVE`, `HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. Each level is a superset of the controls
above it. `HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not in
a debug line, not in a stack trace, not in a crash report (`12` §2, §5.2).

## Field classification
`In logs` and `In analytics` are the handling columns from `12-data-classification.md` §3.

| Field | Level | In logs | In analytics | Notes |
|---|---|---|---|---|
| `id` | INTERNAL | no | no | opaque identifier; used as `resource_id` |
| `tenant_id` | SENSITIVE | yes | aggregate only | isolation key, never a secret |
| `given_name`, `family_name` | HEALTH_INFORMATION | **pseudonymised only** | **never** | direct identifiers; search keys |
| `preferred_name` | HEALTH_INFORMATION | pseudonymised only | never | |
| `date_of_birth` | HEALTH_INFORMATION | pseudonymised only | year band only | retention clock input |
| `sex_at_birth` | HEALTH_INFORMATION | never | aggregate only | clinical attribute |
| `gender_identity` | HIGHLY_SENSITIVE | **never** | **never** | discrimination risk |
| `medicare_number` | **HIGHLY_SENSITIVE** | **never** | **never** | field-encrypted; **always masked** in responses |
| `medicare_blind_index` | **HIGHLY_SENSITIVE** | **never** | **never** | keyed HMAC; equality only; **always masked** |
| `ihi` | **HIGHLY_SENSITIVE** | **never** | **never** | field-encrypted; **always masked** in responses |
| `ihi_blind_index` | **HIGHLY_SENSITIVE** | **never** | **never** | keyed HMAC; equality only; **always masked** |
| `address_line`, `suburb`, `state`, `postcode` | HEALTH_INFORMATION | never | never | direct identifiers |
| `phone`, `email` | HEALTH_INFORMATION | never | never | direct identifiers |
| `deceased_at` | SENSITIVE | no | no | blocks certain operations |
| `merged_into_patient_id` | INTERNAL | yes | no | merge lineage; not patient content |
| `deleted_at` | INTERNAL | yes | no | a soft-deleted row is still personal information |
| `created_at`, `updated_at` | INTERNAL | yes | no | |

> **Note.** `12-data-classification.md` §3 classes `medicare_number` and `ihi` as `HEALTH_INFORMATION`
> and `04-database-erd.md` §3.4 classes `medicare_number` as `SENSITIVE` and `ihi` as `HIGHLY_SENSITIVE`.
> This document applies the **stricter** level to both and masks both, per `HIGHLY_SENSITIVE` handling.
> The divergence is logged as an open item.

## Residency
All fields are stored in the Australian production region (`ap-southeast-2`); every AWS resource is
region-pinned (`13-data-residency.md` §1). No third party receives patient data in the MVP. A
soft-deleted row is retained in the same region until purged under the retention schedule.

## Audit event catalogue
Action names use doc 07's **lowercase dotted** form (`07-audit-architecture.md` §1, §2).

| Event | Story / PRD label | Trigger | Extra envelope fields (no PHI values) |
|---|---|---|---|
| `patient.created` | `PATIENT_CREATED` (`20` §3) | successful create | `resource_id`, `field_set` (names only) |
| `patient.read` | `PATIENT_VIEWED` (`20` §3) | any read, list, search or duplicate lookup — **including denials** | `resource_id`, `care_relationship_id`, `purpose` |
| `patient.updated` | `PATIENT_UPDATED` (`20` §3) | successful `PATCH` | `resource_id`, `changed_fields` (names only), `reason` |
| `patient.merged` | `PATIENT_MERGED` (`20` §3; `22` US-14) | successful merge | survivor `resource_id`, merged id, `reason`, `step_up` |
| `patient.merge_reversed` | `PATIENT_MERGE_REVERSED` (`20` §3; `22` US-14) | successful reversal | `resource_id`, merge reference, `reason`, `step_up` |
| `patient.exported` | `patient.export` (`07` §1); `PATIENT_EXPORT_STARTED` (`06` §8) | bulk or single export | `record_count`, `purpose`, `step_up` |

Two label divergences are recorded, not silently reconciled:
- `PATIENT_IDENTIFIER_VIEWED` (`20` §3) and `PATIENT_DUPLICATE_DETECTED` (`22` US-10) have **no** action
  in `07-audit-architecture.md` §1. Duplicate detection therefore emits `patient.read` with the refusal
  reason; adding a dedicated action requires the table in doc 07 §1 to be extended first.
- `patient.merged` and `patient.merge_reversed` are **not** in `07-audit-architecture.md` §1 either. Per
  that document's rule (no module invents an action name outside the table without adding it there
  first), doc 07 §1 must be extended before build. Logged as an open item.

## Standard envelope
`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason,
source_ip, request_id, correlation_id, prev_hash, hash` (`07-audit-architecture.md` §2). The envelope
carries no clinical payload: identifier values, names and dates of birth never appear. `result` is
`SUCCESS`, `DENIED`, `FAILED` or `UNKNOWN`. The audit store is append-only — the app role holds
`INSERT` and `SELECT` only — and **denied and failed attempts are audited with the same fidelity as
successes**.

## Retention and deletion
- **At least 7 years from the last clinical service**; **pediatric records until age 25** — the periods
  the source cites from NSW s 25 and Victoria HPP 4.2 (`14-retention-and-deletion.md` §2, patient
  records row). Other jurisdictions are unverified.
- **Hard deletes are disallowed.** Soft delete (`deleted_at`) then a scheduled purge by the retention
  role only; the app role has no `DELETE` grant (`04-database-erd.md` §6; `14` §3.1).
- An **APP 12 access or APP 13 correction** triggers an **audited correction** (an appended correction
  event) or **archiving**, never a database `DELETE`. The original is not overwritten (`14` §3.5).
- Legal hold suspends purge; a missing legal-hold evaluation aborts the purge run (fail closed).
- Per-jurisdiction periods, and which rule governs a patient who moves between jurisdictions, are
  **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Per-jurisdiction retention periods for patient records | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| `patient.merged` / `patient.merge_reversed` / `patient.duplicate_detected` are absent from `07-audit-architecture.md` §1 | Security Lead | OPEN |
| Medicare/IHI level divergence between `12` §3 and `04` §3.4 — this doc applies the stricter level | Privacy Officer | OPEN |
| APP 9 basis for each use of a Medicare number or IHI | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
