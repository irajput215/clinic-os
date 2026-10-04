---
doc_id: FEAT-DOC-05
title: Documents, data and audit
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: data and audit

## Classification levels

`12-data-classification.md` §1 defines **seven** levels, and the ladder is a containment ladder —
each level is a superset of the controls above it:

| Level | Meaning in this feature |
| --- | --- |
| `PUBLIC` | Nothing in this feature. A document is never public |
| `INTERNAL` | Storage plumbing: `mime_type`, `size_bytes`, `scan_state`, `scan_engine_version` |
| `CONFIDENTIAL` | `object_key` — an access path, never logged in full; `uploaded_by` |
| `SENSITIVE` | `id`, `sha256`, `deleted_at` |
| `HEALTH_INFORMATION` | A document whose content identifies a patient in a clinical context |
| `HIGHLY_SENSITIVE` | **Document content**, `original_filename` (filenames routinely contain patient names) |
| `SECRET` | The presigned URL and the KMS data key — shared secrets that defeat a control if disclosed |

## Field map

| Field / item | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- |
| `id` | SENSITIVE | pseudonymous | aggregate only | `12 §3` |
| `tenant_id` | INTERNAL | yes | hashed tenant key only | never a content dimension |
| `patient_id` | HEALTH_INFORMATION | pseudonymous | pseudonymous | never a name |
| `object_key` | CONFIDENTIAL | **never in full** | never | an access path; `12 §3` |
| `original_filename` | HIGHLY_SENSITIVE | **never** | **never** | often contains a patient name |
| `mime_type` | INTERNAL | yes | aggregate only | from magic bytes |
| `size_bytes` | INTERNAL | yes | aggregate only | |
| `sha256` | SENSITIVE | never | never | integrity evidence and a weak content fingerprint |
| `scan_state`, `scan_engine_version` | INTERNAL | yes | aggregate only | pipeline state, safe without payload |
| `uploaded_by` | CONFIDENTIAL | pseudonymous | pseudonymous | attributable human action |
| `deleted_at` | SENSITIVE | yes | aggregate only | |
| **Document content (object bytes)** | HIGHLY_SENSITIVE | **never** | **never** | private bucket; presigned URL only |
| OCR / extracted text (feature 09) | HIGHLY_SENSITIVE | never | never | out of scope here |
| Presigned URL | SECRET | **never** | never | transient; never persisted, cached or emailed |
| KMS data key | SECRET | never | never | envelope encryption; `02 §5` |

`HIGHLY_SENSITIVE` never reaches a log line, an analytics pipeline or error telemetry — not in a debug
line, not in a stack trace, not in a crash report, not in a support ticket (`12 §2`, §5.2).

## Residency

Documents and their metadata are stored in `ap-southeast-2` and processed only there
(`21-technical-design.md` §5; `11-tga-inbox-pipeline.md` §8). Two flows are **not** settled:

| Flow | Question | Owner | Status |
| --- | --- | --- | --- |
| Malware scanning | The scan service receives document content. Self-hosted ClamAV in-region is one option; a managed service may process content outside Australia. Region, sub-processor list and contract terms are unvalidated | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Any future fetch-from-URL import | Would introduce an outbound request and a second processing location | Security Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |

Until a row above is settled, the flow is not used for production health information
(`13-data-residency.md` §1 conditions 1–5).

## Audit event catalogue

| Event | Trigger | Key fields beyond the envelope |
| --- | --- | --- |
| `document.uploaded` | A `documents` row is created and the object is stored | `document_id`, `patient_id`, `size_bytes`, `sha256`, `source`, `scan_state` |
| `document.viewed` | A presigned URL is issued, and again when the object is fetched where observable | `document_id`, `purpose`, `ttl_seconds = 300` |
| `document.scan_failed` | Verdict is `INFECTED`, `ERROR`, or validation failed before storage | `document_id`, `verdict_class`, `engine_version`, `quarantine_ref` |
| `document.deleted` | Soft delete applied | `document_id`, `reason_code` |
| `document.denied` | Any refused upload, read, mint or delete | `attempted_action`, `denial_reason` (permission, tenant, scan_state, relationship, validation) |

**Registration required before use.** None of these four names appears in
`07-audit-architecture.md` §1, which is the authoritative action vocabulary, and no `documents.*`
domain exists in it. The closest registered names belong to the inbox pipeline and mean something
different:

| Proposed name | Registered equivalent | Gap |
| --- | --- | --- |
| `document.uploaded` | `tga_document.ingest` — "document received into the secure inbox" | inbox-specific; does not cover a clinician upload |
| `document.viewed` | `documents.read` (`11 §11`) — "a presigned URL is issued" | `documents.read` is not itself in `07 §1` |
| `document.scan_failed` | `tga_document.malware_detected`, `tga_document.validation_failed` | inbox-specific; no `ERROR` verdict event |
| `document.deleted` | none | **absent entirely** |

`07 §1` states that no module invents an action name outside that table without adding it there
first. The four names above are therefore **proposed, not approved**: they must be registered in
`07-audit-architecture.md` §1 with a resource type before any of them is emitted. `TGA_DOCUMENT`
already exists in the envelope's `resource_type` enum, so no new resource type is needed.

## Standard envelope

Every event carries the envelope from `07-audit-architecture.md` §2 unchanged: `event_id`, `timestamp`
(UTC, server clock), `tenant_id` (from context, never the body), `actor_id` (or `SYSTEM` with the job
name in `reason`), `actor_role` at decision time, `action`, `resource_type` (`TGA_DOCUMENT`),
`resource_id`, `result` (`SUCCESS`/`DENIED`/`FAILED`/`UNKNOWN`), `reason` (controlled code),
`source_ip` (`/24` or `/48` truncated on export), `request_id`, `correlation_id`, `prev_hash`, `hash`.

The envelope carries no clinical payload. A document filename, a content excerpt or an object key is
not an envelope field. The audit store is append-only: the app role holds `INSERT` and `SELECT` only,
and **denied and failed attempts are audited with the same fidelity as successes**.

## Retention

| Item | Position | Owner | Status |
| --- | --- | --- | --- |
| Document row and object | Never hard-deleted by the application. Soft delete sets `deleted_at`; the object transitions to a retention prefix by lifecycle rule after the retention period, subject to a legal-hold check | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Audit events about documents | Kept for the period the adviser confirms; never row-deleted (`14-retention-and-deletion.md` §6) | Privacy Officer | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Superseded object versions | Retained while versioning is on; no automatic expiry until the retention rule is confirmed | Head of Platform | OPEN |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Register the four `document.*` action names in `07-audit-architecture.md` §1, or adopt the registered alternatives | Security Lead | OPEN — blocks R10 |
| Malware-scan service residency and sub-processor position | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Retention period for document objects, versions and their audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| `object_key` is `CONFIDENTIAL` in `12 §3` but `SENSITIVE` in `04 §3.9`; this doc applies the stricter label | Privacy Officer | OPEN |
