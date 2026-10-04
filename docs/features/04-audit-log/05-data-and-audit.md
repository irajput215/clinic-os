---
doc_id: FEAT-AUD-05
title: Audit log, data and audit
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 12-data-classification, 14-retention-and-deletion
source:
  - Privacy Act 1988 (Cth), APP 11
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2, §7, §9, §10
  - clinic-os-secure-by-design/12-data-classification.md §1, §3, §4
  - clinic-os-secure-by-design/13-data-residency.md §3, §6
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3.3, §3.5, §3.6
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Field classification

Levels are from doc 12 §1, which defines **seven**: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`,
`HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`. Doc 12 §3 places audit events at **SENSITIVE**:
information whose disclosure harms an individual or a clinic and that is not itself health information.
`resource_id` is the exception — it points at a clinical object and is `HEALTH_INFORMATION`.

| Field | Level | Log | Audit | Analytics | Non-prod | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | SENSITIVE | yes | yes | never | synthetic | assigned by the writer |
| `timestamp` | SENSITIVE | yes | yes | aggregate only | synthetic | timeline evidence |
| `tenant_id` | SENSITIVE | yes | yes | aggregate only | de-identified | isolation key, never a secret |
| `actor_id` | SENSITIVE | pseud | yes | never | synthetic | workforce identity; `SYSTEM` for jobs |
| `actor_role` | SENSITIVE | yes | yes | aggregate only | synthetic | role at decision time |
| `action` | SENSITIVE | yes | yes | aggregate only | synthetic | from the catalogue below |
| `resource_type` | SENSITIVE | yes | yes | aggregate only | synthetic | |
| `resource_id` | HEALTH_INFORMATION | pseud | yes | never | synthetic | points at a clinical object |
| `result` | SENSITIVE | yes | yes | aggregate only | synthetic | allow, deny or failure |
| `reason` | SENSITIVE | **never** | yes | never | synthetic | may contain typed justification; captured, never logged |
| `source_ip` | SENSITIVE | yes | yes | never | synthetic | personal information in some contexts |
| `request_id` | INTERNAL | yes | yes | never | synthetic | joins log line to event |
| `correlation_id` | INTERNAL | yes | yes | never | synthetic | cross-service intent |
| `prev_hash`, `hash` | INTERNAL | yes | yes | never | synthetic | tamper evidence |
| `metadata` (per action) | allow-listed | no | allow-listed keys only | never | synthetic | new key is a deliberate change with a test |

## What may never be in an audit payload

Never: clinical narrative, medicine or dose text, diagnosis codes, Medicare numbers, Individual
Healthcare Identifiers, full prescriptions, OCR text from ingested documents, document bodies, secrets,
tokens, session identifiers, **or a full request body from a clinical endpoint**. The `metadata` object
is allow-listed by key in code, so a new key is a deliberate change with a test (doc 07 §7, §11).
`HIGHLY_SENSITIVE` and `SECRET` values never reach the audit payload in any form; the action is recorded
and the value is not (doc 12 §4).

## Residency

The trail is stored in `ap-southeast-2` and streamed to an S3 Object Lock bucket in the same region
(`13 §6` DR-11). Sensitive healthcare information stays in Australia: region pinning by configuration,
and no resource may hard-code another region. No third party receives audit data in the MVP.

## The action catalogue (doc 07 §1)

The canonical action name is the value in the `action` field, **lowercase dotted form** (doc 07 §2).
This list is closed:

| Resource type | Actions |
| --- | --- |
| `SESSION` | `auth.login`, `auth.logout`, `auth.login_failed`, `auth.step_up`, `auth.step_up_failed` |
| `PATIENT` | `patient.read`, `patient.create`, `patient.update`, `patient.export` |
| `CLINICAL_RECORD` | `clinical_record.read`, `clinical_record.write` |
| `PRESCRIPTION` | `prescription.create`, `prescription.modify`, `prescription.sign`, `prescription.dispatch`, `prescription.dispatch_blocked`, `prescription.reject`, `prescription.dispatch_failed` |
| `TGA_APPROVAL` | `tga_approval.create`, `tga_approval.modify`, `tga_approval.state_change`, `tga_approval.match`, `tga_approval.verify` |
| `TGA_DOCUMENT` | `tga_document.ingest`, `tga_document.extract` |
| `USER` | `user.permission_change`, `user.create`, `user.deactivate` |
| `TENANT` | `tenant.security_config_change` |
| `INTEGRATION` | `integration.request` |
| `AUDIT` | `audit.read` |

**No new action name may be invented.** A new action must be registered in doc 07 §1 first, by a change
to the source contract, before any code emits it. A missing mandatory event is a defect, and an event
coverage test asserts the list.

Events beyond the envelope carry the mandatory per-action fields from doc 07 §1 — for example
`prescription.dispatch_blocked` carries `block_reason` and `approval_id`, and `audit.read` carries
`query_filters` and `result_count`.

## Retention

The obligation to hold access records is *Privacy Act 1988* (Cth) APP 11 (security of personal
information, including the access-accounting expectation) and the state and territory health records
legislation. Status: **REQUIRES LEGAL/REGULATORY VALIDATION** with the Head of Legal and Compliance; this
document does not choose a period. The mechanism is: an `audit_log` partition per month, an Object Lock
retention period per partition, and a partition-drop job that runs only after the retention period has
elapsed and no legal hold applies. Deletion of a single audit event is not a feature; expiry is the only
removal mechanism, and it operates on whole partitions.

| Record class | Working assumption (design only, not a decision) | Source |
| --- | --- | --- |
| Health-record-linked audit events | 7 years | `07 §4` — marked REQUIRES LEGAL/REGULATORY VALIDATION |
| Purely authentication events | 12 months | `07 §4` — marked REQUIRES LEGAL/REGULATORY VALIDATION |

A deletion request cannot delete the audit event that recorded the request: the trail is the evidence
that the request was handled (doc 14 §3.5). A hold is a recorded decision with a scope, a reason, an
owner and a 90-day review; it blocks partition drop, and release resumes the next run (doc 14 §3.6).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Retention period per event class and per jurisdiction | Head of Legal and Compliance | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Action-name convention: doc 07 §1 lowercase dotted vs doc 04 §3.10 `PATIENT_READ` | Security Lead | OPEN — doc 07 adopted |
| `record.purged` appears in `14 §3.3` but is **not** in the doc 07 §1 catalogue; the certificate needs a registered action | Head of Legal and Compliance + Security Lead | OPEN — no action may be invented |
| Doc 21 §4 names operations in prose (`webhook receipt`, `dispatch confirmation`, `reconciliation outcome`) that have no doc 07 §1 action name | CTO | OPEN |
| `reason` classification: `HIGHLY_SENSITIVE` in doc 04 §3.10 vs `SENSITIVE` in doc 12 §3 — this doc applies `SENSITIVE` but never logs it | Privacy Officer | OPEN |
