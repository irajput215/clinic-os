---
doc_id: OZ-FEAT-10-DATA
title: "Prescription safety gate — data classification and audit events"
owner: Privacy Officer + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-10
phase: 03-phase-3-eprescribing
gate: [4, 6]
source:
  - clinic-os-secure-by-design/12-data-classification.md
  - clinic-os-secure-by-design/09-prescription-safety-gate.md
  - clinic-os-secure-by-design/07-audit-architecture.md
repo_docs:
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Why this feature sits at the top of the classification ladder

A prescription reveals the patient's condition, the medicine, the dose and the pattern of use; in
combination it identifies a person receiving an unapproved therapeutic good. Source doc 12 classifies
prescriptions and their payloads as **`HIGHLY_SENSITIVE`**, which carries a hard prohibition:

> `HIGHLY_SENSITIVE` never appears in an application log, an analytics pipeline or error telemetry — not
> in a debug line, not in a stack trace, not in a request-body capture, not in a third-party crash report.

The audit trail records **that** a dispatch happened, under which approval, at which instant, and with
which outcome. It does **not** record what was prescribed.

## Field classification

The seven levels are `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`,
`HIGHLY_SENSITIVE`, `SECRET` (source doc 12 §1).

| Field | Table | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- | --- |
| `medicine_name` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | product plus patient reveals treatment |
| `dosage_form` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | part of the approval grain and the clinical decision |
| `dose_instruction` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | directions are clinical content |
| `quantity`, `repeats` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | infers duration and pattern of use |
| `schedule8_flag` | `prescriptions` | HIGHLY_SENSITIVE | **never** | **never** | controlled medicine status |
| `prescription_id` | `prescriptions` | HIGHLY_SENSITIVE | pseudonymous | aggregate only | prescribing event identifier |
| `prescriber_id` | `prescriptions` | SENSITIVE | pseudonymous | pseudonymous | practitioner identifier |
| `dispatch_status` | `prescriptions` | SENSITIVE | yes | aggregate only | operational state, safe without payload |
| `parchment_reference` | `prescriptions` | SENSITIVE | **never** | **never** | external rail reference linking to the script |
| `idempotency_key` | `dispatch_attempts` | INTERNAL | pseudonymous | no | server-computed hash; no clinical content |
| `request_payload_hash` | `dispatch_attempts` | INTERNAL | yes | no | proof of request identity **without** the payload |
| `provider_event_id` | `dispatch_attempts` | SENSITIVE | pseudonymous | no | webhook deduplication key |
| `error_class`, `outcome_class` | `dispatch_attempts` | INTERNAL | yes | aggregate only | closed vocabulary, no free text |
| `block_reason` | `audit_log` | SENSITIVE | yes | aggregate only | closed vocabulary |
| Provider credential, webhook signing secret | — | **SECRET** | **never** | never | secret store only, referenced by ARN |

## Residency

All fields are stored in the Australian production region. No third party receives them in the MVP.
The Parchment rail is the one outbound flow and is governed by FEAT-13.

## Audit events

Every event carries the standard envelope from doc 07:
`timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason,
source_ip, request_id, correlation_id`. `result` is `SUCCESS | DENIED | FAILED | UNKNOWN` — an unknown
provider outcome records `FAILED` with `reason = UNKNOWN`, never `SUCCESS`.

| Event | Trigger | Result | Key fields (no PHI values) |
| --- | --- | --- | --- |
| `prescription.create` | draft created | SUCCESS | actor, tenant, prescription_id, request_id |
| `prescription.sign` | signature applied with step-up | SUCCESS | actor, prescription_id, step_up = true |
| `auth.step_up_failed` | stale or missing step-up | DENIED | attempted operation and resource |
| **`prescription.dispatch_blocked`** | **gate refused at steps 4–9** | **DENIED** | **`block_reason`; never suppressed** |
| `prescription.dispatch` | gate passed and queued | SUCCESS | approval_id, idempotency_key |
| `prescription.dispatch` | provider confirmed | SUCCESS | reason = `PROVIDER_CONFIRMED` or `WEBHOOK_CONFIRMED` |
| `prescription.dispatch_failed` | provider rejected | FAILED | error_class, **no payload** |
| `prescription.dispatch_failed` | timeout | **UNKNOWN** | moves the prescription to `REQUIRES_RECONCILIATION` |
| `prescription.dispatch` / `_failed` | reconciliation resolved | SUCCESS / FAILED | reason = `RECONCILED`, original `correlation_id` |
| `AUTHZ_DENIED`, `AUTHZ_CARE_RELATIONSHIP_DENIED` | steps 2–3 refused | DENIED | attempted route and resource |
| `prescription.reject` | reversal | SUCCESS | reason required |

**A blocked dispatch is recorded even when the caller cannot see the approval state**, because the
pattern of blocked attempts is the signal: repeated attempts by one actor, or attempts across many
patients, feed anomaly detection.

## Append-only enforcement

```sql
GRANT SELECT, INSERT ON audit_log TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
```

The app role is not the table owner and has no `BYPASSRLS`. A failure to write an event for an audited
operation **fails the operation** — for dispatch that means the transaction rolls back and no provider
call is made.

## Retention

Prescription and dispatch records are retained with the patient's clinical record and are **never
deleted** while that record is active. `audit_log` events are retained for the period owned by the
Compliance Lead and are not deleted while a gate or an incident is open. Per-jurisdiction periods are
**REQUIRES LEGAL/REGULATORY VALIDATION**.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Audit retention for prescription and dispatch events per jurisdiction | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether a legal hold suspends dispatch-record retention | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether `block_reason` categories are disclosable to a pharmacy on request | CSO + legal | OPEN |
| Retention period for `request_payload_hash` | Compliance Lead | OPEN |
