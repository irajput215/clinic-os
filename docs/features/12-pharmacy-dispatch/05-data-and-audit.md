---
doc_id: OZ-FEAT-12-DATA
title: "Pharmacy dispatch — data classification and audit"
owner: Privacy Officer + Head of Platform
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-12
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/12-data-classification.md
  - clinic-os-secure-by-design/07-audit-architecture.md
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 06-test-plan.md
---

# Data and audit

## Field classification

The seven levels are `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`,
`HIGHLY_SENSITIVE`, `SECRET` (source doc 12 §1).

| Field | Table | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- | --- |
| `id`, `tenant_id` | both | INTERNAL | yes | aggregate only | identifiers only |
| `provider`, `event_type`, `process_result` | `webhook_events` | INTERNAL | yes | aggregate only | no clinical content |
| `signature_verified` | `webhook_events` | INTERNAL | yes | aggregate only | outcome of verification |
| `payload_sha256` | `webhook_events` | INTERNAL | yes | no | proof of identity **without** the payload |
| `provider_event_id` | `webhook_events` | SENSITIVE | pseudonymous | no | dedupe key |
| `provider_occurred_at`, `provider_seq`, `received_at` | `webhook_events` | SENSITIVE | no | no | timing correlation |
| `source_ip`, `correlation_id` | `webhook_events` | SENSITIVE | pseudonymous | no | security and trace |
| **Raw webhook payload (in-memory only)** | — | **HIGHLY_SENSITIVE** | **never** | **never** | retained for signature verification only; never logged, not persisted on the normal path |
| Quarantined payload (**OPEN-2**) | quarantine store | **HIGHLY_SENSITIVE** | **never** | **never** | access restricted to a named operator role |
| `prescription_id` | `pharmacy_dispatches` | HIGHLY_SENSITIVE | pseudonymous | aggregate only | links to the prescription record |
| `pharmacy_id`, `dispensed_by`, `provider_dispatch_ref` | `pharmacy_dispatches` | SENSITIVE | pseudonymous | no | identifiers and external references |
| `status`, `dispensed_at`, `received_at` | `pharmacy_dispatches` | SENSITIVE | yes | aggregate only | operational state, safe without payload |
| `quantity_dispensed` | `pharmacy_dispatches` | HIGHLY_SENSITIVE | **never** | **never** | infers duration and pattern of use |
| `rejection_reason_code` | `pharmacy_dispatches` | SENSITIVE | code only | aggregate only | free text never stored or logged |
| `last_event_seq` | `pharmacy_dispatches` | INTERNAL | yes | no | ordering source |
| Webhook signing secret | — | **SECRET** | **never** | never | Secrets Manager only, referenced by ARN |

`HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not a debug
line, a stack trace, a crash report or a request-body capture (`12 §5.2`). The raw webhook payload is the
highest-risk object in this feature and exists in memory only for the duration of verification.

## Residency

All rows are stored in the Australian production region (`ap-southeast-2`, `21 §5`). The provider is the
one **inbound** sub-processor for this feature; its contract terms, processing location and support
access are **REQUIRES LEGAL/REGULATORY VALIDATION** (OPEN-4).

## Audit events

Every event carries the standard envelope from `07 §2`: `timestamp, tenant_id, actor_id, actor_role,
action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id`. A webhook has
no human actor: `actor_id` is the provider **service identity** and `actor_role = INTEGRATION`; whether
the envelope permits a non-human actor is OPEN-5.

| Event | Trigger | In `07 §1`? | Key fields (no clinical payload) |
| --- | --- | --- | --- |
| `integration.request` | event arrives and verifies | yes | provider, outcome, latency_ms, correlation_id |
| `prescription.dispatch` | state effect committed (`reason = WEBHOOK_CONFIRMED`) | yes | resource_id, approval_id, idempotency_key, provider |
| `prescription.dispatch_failed` | processing failure or provider outage | yes | error_class, outcome_class = UNKNOWN |
| `integration.webhook_rejected` | unverified or stale-signature drop | **absent — proposed** | provider, reason, source_ip |
| `integration.webhook_quarantined` | payload maps to no tenant | **absent — proposed** | provider, payload_sha256, reason |
| `integration.webhook_duplicate` | dedupe hit | **absent — proposed** | provider, provider_event_id |
| `pharmacy.dispatch.received` | receipt created | **absent — proposed** | resource_id, provider_dispatch_ref |
| `pharmacy.dispatch.confirm` | pharmacy confirms dispense | **absent — proposed** | resource_id, actor, step_up |
| `pharmacy.dispatch.reject` | pharmacy rejects with a reason code | **absent — proposed** | resource_id, reason code |

Names marked **absent** do not exist in `07 §1`. `07 §1` forbids inventing an action name outside that
table without adding it there first, so they are **OPEN-6** and must be added upstream before build.
`integration.request` is defined in `07 §1` for a call **to** an external provider; reusing it for an
**inbound** arrival is a reading, not a quotation, and is recorded in OPEN-6.

Denied and failed attempts are audited with the same fidelity as successes: every `401` drop, every
duplicate, every quarantine and every refusal writes an event.

## Retention and deletion

- `webhook_events` is append-only by grant and retained at least for the dedupe window plus the audit
  period; the exact period is OPEN-7.
- `pharmacy_dispatches` is retained with the patient's clinical record and is **never hard-deleted** by
  the app; the app role has no `DELETE` grant.
- A quarantined payload's retention, and whether the raw body may be persisted at all, are unresolved
  (OPEN-5) and **REQUIRES LEGAL/REGULATORY VALIDATION**.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| OPEN-4 provider contract terms, processing residency and sub-processor status | Head of Legal and Compliance | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 quarantined-payload retention and whether the raw body may be persisted | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-6 the proposed action names absent from `07 §1`, and inbound reuse of `integration.request` | Compliance Lead + CTO | OPEN |
| OPEN-7 retention period for `webhook_events` | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Non-human actor representation in the `07 §2` envelope | Security Lead | OPEN |
