---
doc_id: OZ-FEAT-04-DATA
title: "FEAT-04 — TGA Approval Module: Data Classification, Residency & Audit Ledger"
owner: CTO + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - clinic-os-secure-by-design/07-audit-architecture.md
  - clinic-os-secure-by-design/12-data-classification.md
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Fields and classification

Levels are from doc 12 §1, which defines **seven**: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`,
`HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`.

| Field | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- |
| `id`, `tenant_id` | INTERNAL | yes | yes | identifiers only |
| `patient_id` | SENSITIVE | opaque ID only | no | never log names |
| `category`, `dosage_form` | HIGHLY_SENSITIVE | **no** | **no** | clinical decision data (doc 12 §3) |
| `approval_reference` | SENSITIVE | no | no | regulator reference |
| `valid_from`, `valid_to` | SENSITIVE | no | no | |
| `status` | SENSITIVE | yes | aggregate only | operational state, safe without payload |
| `source_document_id` | SENSITIVE | no | no | key into the private store |
| `created_by`, `verified_by` | SENSITIVE | pseudonymous | no | practitioner identifiers |
| `revoked_reason_code` | SENSITIVE | code only | no | free text never logged |
| Source document (PDF) | HIGHLY_SENSITIVE | no | no | presigned URL only |

`HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not in a debug
line, not in a stack trace, not in a crash report.

## Residency
All fields are stored in the Australian production region. No third party receives them in the MVP.
Source documents stay in the private document store. Any future OCR vendor is OPEN and
**REQUIRES LEGAL/REGULATORY VALIDATION** before receiving patient data.

## Audit events emitted

| Event | Trigger | Key fields (no PHI values) |
| --- | --- | --- |
| `approval.created` | successful create | actor, tenant, approval_id, patient_id, request_id |
| `approval.verified` | successful verify | actor, approval_id, status before and after |
| `approval.revoked` | successful revoke | actor, approval_id, reason code |
| `approval.expired` | system job | approval_id, job_id |
| `approval.read` (emitted as `tga_approval.read`, registered 2026-10-07) | patient-level read; detail read; one per register page | actor, role, patient_id, count; for the register `query_filters` and count |
| `approval.denied` | any refused action | actor, attempted action, denial reason (permission, tenant, validation, transition) |
| `gate.check` | each gate lookup | approval_id or none, result, caller |

Each event uses the standard envelope from doc 07: `timestamp, tenant_id, actor_id, actor_role, action,
resource_type, resource_id, result, reason, source_ip, request_id, correlation_id`. The audit store is
append-only; the app role holds `INSERT` and `SELECT` only, and **denied and failed attempts are audited
with the same fidelity as successes**.

## Retention and deletion
Status: OPEN — **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.

Working assumption for design only: approvals are never hard-deleted by the app (R13). A deletion
request routes to a manual process. Audit events about approvals are kept for the period the adviser
confirms.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Retention period for approval records and their audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| `category`/`dosage_form` are `HIGHLY_SENSITIVE` per doc 12 §3 but `HEALTH_INFORMATION` per doc 04 §3.6 — this doc applies the stricter level | Privacy Officer | OPEN |
