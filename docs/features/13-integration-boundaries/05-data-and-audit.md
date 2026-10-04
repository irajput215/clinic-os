---
doc_id: OZ-FEAT-13-DATA
title: "Integration boundaries — data and audit"
owner: Head of Platform + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-13
phase: 03-phase-3-eprescribing
gate: [5]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §5.1
  - clinic-os-secure-by-design/13-data-residency.md §3
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2
  - clinic-os-secure-by-design/04-database-erd.md §3.12
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Fields and classification

Levels are from `12` §1, which defines **seven**: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`,
`HEALTH_INFORMATION`, `HIGHLY_SENSITIVE`, `SECRET`.

| Field / artefact | Level | In logs | In analytics | Notes |
|---|---|---|---|---|
| `id`, `tenant_id`, `provider_code` | INTERNAL | yes | yes | identifiers only; `provider_code` is a closed set |
| `integration_credentials_refs.secret_arn` | **SECRET** | **no** | **no** | a Secrets Manager ARN, never a secret value. `04` §3.12 classes the column SECRET; `12` §5.1 rule 1 classes a pointer CONFIDENTIAL — this doc applies the **stricter** level (OPEN) |
| Provider credential value, signing secret, IdP client secret | **SECRET** | **no** | **no** | **never stored** in a column, image, env var or repo; referenced by ARN and read at runtime into memory; never logged, traced, exported or put in a crash report |
| IdP access / refresh / ID token | **SECRET** | **no** | **no** | held in memory; only a one-way hash is persisted for revocation; never exported |
| `status`, `rotated_at`, `expires_at`, `last_used_at` | INTERNAL | yes | no | credential lifecycle metadata |
| `webhook_events.raw_payload_ref` and the raw request body | HIGHLY_SENSITIVE | **no** | **no** | retained for signature verification and replay/dedupe only; the body is **never logged** and is not dereferenced |
| `provider_event_id`, `event_timestamp`, `received_at`, `processing_result` | SENSITIVE | yes | aggregate only | dedupe and ordering metadata |
| `signature_verified`, `correlation_id`, `request_id` | INTERNAL | yes | no | operational metadata |
| Parchment outbound prescription payload | HIGHLY_SENSITIVE | **no** | **no** | the prescription is the clinical record; the integration log holds no medicine, directions or address |
| Tyro payment amount, invoice reference, provider token | SENSITIVE | reference only | aggregate only | card data never enters the platform (`10` §6) |
| Notification recipient address or number and message content | HEALTH_INFORMATION | **no** | **no** | minimum content only (`16` §1.1) |
| Integration log record | CONFIDENTIAL | n/a | no | correlation ID, provider, operation, outcome class, latency, error class only (`14`) |
| `integration.request`, provider-effect audit events | SENSITIVE | n/a | no | `provider`, outcome, latency, correlation ID; **no clinical payload** |

`SECRET` values are never written to an application database column, logged, traced, exported, placed in
a crash report, or committed to Git (`12` §5.1). `HIGHLY_SENSITIVE` never reaches a log line, an
analytics pipeline or error telemetry — not in a debug line, not in a stack trace.

## Residency and cross-border register

All registered flows are recorded in the residency register (`13` §3). **No row in that register is
`OFFSHORE-APPROVED`**, and every non-onshore flow fails the five-condition test today:

| Flow ID | Source → destination | Data | Residency | Five-condition result |
|---|---|---|---|---|
| DR-04 | API → Parchment e-prescribing rail | Prescription payload, patient and prescriber identifiers | **UNKNOWN** | Not passed |
| DR-06 | TGA correspondence channel → inbox (`ap-southeast-2`) | Approval correspondence, attachments | **UNKNOWN** | Not passed |
| DR-07 | Inbox worker → OCR service (vendor `V-07`) | Document images, extracted text | **UNKNOWN** | Not passed |
| DR-08 | API → Tyro payments | Amount, invoice reference, provider token | **UNKNOWN**, likely onshore | Not passed |
| DR-09 | API → Identity provider (OIDC) | Workforce identifier, email, auth events | **UNKNOWN** | Not passed |
| DR-10 | API → Notification provider | Recipient contact detail, notification content | **UNKNOWN** | Not passed |
| DR-14 | API and infrastructure → logging and telemetry | Application, security, integration logs | ONSHORE (self-managed) | Implemented |
| DR-15 | API and frontend → error monitoring | Stack traces, pseudonymous metadata; HIGHLY_SENSITIVE scrubbed | **UNKNOWN** | Not passed |

Every provider's contractual terms, residency position and sub-processor list is **REQUIRES
LEGAL/REGULATORY VALIDATION** (`16` §2, §6). A vendor claim is not evidence; an executed clause, a
configuration screenshot or a data processing addendum is. No sub-processor list has been sighted.

## Audit event catalogue

The catalogue is `07` §1. This feature emits the following; **no module invents an action name** outside
that table without adding it there first.

| Action | Trigger | Result | Fields beyond the envelope |
|---|---|---|---|
| `integration.request` | Any outbound provider call | `SUCCESS` / `FAILED` / `UNKNOWN` | `provider`, `outcome`, `latency_ms`, `correlation_id` |
| `integration.request` | Webhook arrival, accepted | `SUCCESS` | `provider`, `outcome`, `correlation_id` |
| `integration.request` | Webhook rejected (signature, replay, old timestamp, unknown tenant) | `DENIED` | `provider`, `reason` |
| `prescription.dispatch` | Provider confirmed, or reconciliation resolved | `SUCCESS` | `approval_id`, `idempotency_key`, `provider`; `reason = PROVIDER_CONFIRMED` / `WEBHOOK_CONFIRMED` / `RECONCILED` |
| `prescription.dispatch_failed` | Provider rejected, 5xx after retries, or timeout | `FAILED` / `UNKNOWN` | `provider`, `error_class`, `outcome_class`; **no payload** |
| `prescription.dispatch_blocked` | Domain check refused the call | `DENIED` | `block_reason`, `approval_id` where known |
| `tga_document.ingest`, `tga_approval.match`, `tga_approval.verify` | TGA ingestion path: document in, candidate match, **human** verification | `SUCCESS` / `DENIED` | as `07` §1; ingestion never writes a gating state |

**Names absent from `07` §1, and therefore not used by this feature:** `10` §7 names a `payment.*`
effect, but no payment action exists in the catalogue; there is no standalone webhook-received or
webhook-rejected action; there is no `integration.reconciled` action (reconciliation writes
`prescription.dispatch` with `reason = RECONCILED`); and there is no credential-rotation event. Editing
the `07` §1 catalogue is a prerequisite to naming any of these — see Open items.

## Standard envelope

Every event carries the full envelope from `07` §2: `event_id, timestamp, tenant_id, actor_id, actor_role,
action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id, prev_hash,
hash`. The audit store is append-only; the app role holds `INSERT` and `SELECT` only. **Denied and failed
attempts are audited with the same fidelity as successes**, and a failure to write an audit event for an
audited operation fails the operation. The intent event commits **before** the external call.

## Retention

| Record | Retention | Status |
|---|---|---|
| Integration logs | 90 days recommended for operational logs; longer where needed for reconciliation | `14` — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Webhook raw payload | Retained for verification/dedupe only; the source gives no period | OPEN — Privacy Officer |
| Audit events (`integration.request`, provider effects) | Per the audit retention period | `14` §2 — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Payment transaction references | Per financial retention | `16` V-05 — **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Credential reference (`secret_arn`) | Life of the vendor relationship; deleted on offboarding after rotation | `04` §3.12; `16` §5 |

## Open items

| Item | Owner | Status |
|---|---|---|
| Write `payment.*`, a standalone webhook action, and a reconciliation action into the `07` §1 catalogue before naming them | Security Lead | OPEN |
| `secret_arn` level: `04` §3.12 says SECRET, `12` §5.1 says a pointer is CONFIDENTIAL | Privacy Officer | OPEN — stricter level applied here |
| Retention for webhook raw payloads and integration logs | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Sub-processor lists and residency positions for every provider | Compliance/Auditor | REQUIRES LEGAL/REGULATORY VALIDATION |
