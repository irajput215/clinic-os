---
doc_id: OZ-FEAT-09-DATA
title: "TGA inbox — data classification, residency and audit"
owner: CTO + Privacy Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/12-data-classification.md §1, §3, §4, §5.4
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2, §7
  - clinic-os-secure-by-design/13-data-residency.md
  - clinic-os-secure-by-design/14-retention-and-deletion.md
  - clinic-os-secure-by-design/16-vendor-register.md §2
repo_docs:
  - 01-requirements.md
  - 03-design.md
  - 04-threat-model.md
  - 06-test-plan.md
---

# Data and audit

## Field classification

The seven levels are `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `SENSITIVE`, `HEALTH_INFORMATION`,
`HIGHLY_SENSITIVE`, `SECRET` (`12` §1). Where `04` §3.7 and `12` §3 disagree, the **stricter** level is
applied and the divergence is recorded. A document is never `PUBLIC`.

| Field / item | Table or store | Level | In logs | In analytics | Notes |
| --- | --- | --- | --- | --- | --- |
| `id`, `tenant_id` | all inbox tables | INTERNAL | yes | aggregate only | identifiers |
| `provider_message_id` | `tga_inbox_messages` | INTERNAL | yes | aggregate only | dedupe key |
| `from_address`, `to_address` | `tga_inbox_messages` | SENSITIVE | **never** | never | `12` §3 calls the sender `CONFIDENTIAL`; the stricter level is applied |
| **`subject`** | `tga_inbox_messages` | **HIGHLY_SENSITIVE** | **never** | **never** | subjects in this pipeline contain patient identifiers |
| `received_at` | `tga_inbox_messages` | SENSITIVE | yes | aggregate only | `04` says INTERNAL, `12` says SENSITIVE; stricter applied |
| `spf_result`, `dkim_result`, `dmarc_result` | `tga_inbox_messages` | INTERNAL | yes | aggregate only | displayed at verification |
| `processing_state` | `tga_inbox_messages` | INTERNAL | yes | aggregate only | pipeline state |
| `raw_object_key`, `object_key` | messages, attachments | CONFIDENTIAL | **never in full** | never | access path; never logged whole |
| **`original_filename`** | `tga_inbox_attachments` | **HIGHLY_SENSITIVE** | **never** | **never** | filenames routinely contain patient names |
| `content_type`, `size_bytes` | `tga_inbox_attachments` | INTERNAL | yes | aggregate only | determined from magic bytes |
| `sha256` | `tga_inbox_attachments` | SENSITIVE | never | never | integrity evidence and a weak content fingerprint |
| `scan_state`, `scanned_at` | `tga_inbox_attachments` | INTERNAL | yes | aggregate only | safe without payload |
| `field_name` | `tga_extraction_results` | HEALTH_INFORMATION | yes | aggregate only | `04` §3.7 says HEALTH_INFORMATION, `12` §3 says INTERNAL; stricter applied |
| **`raw_value`** | `tga_extraction_results` | **HIGHLY_SENSITIVE** | **never** | **never** | OCR text is a clinical document in another form |
| **`accepted_value`** | `tga_extraction_results` | **HIGHLY_SENSITIVE** | **never** | **never** | the human-accepted clinical value |
| `confidence`, `page_number`, `region` | `tga_extraction_results` | INTERNAL | yes | aggregate only | routing and provenance signals, not content |
| `accepted_by` | `tga_extraction_results` | CONFIDENTIAL | pseudonymous | no | attributable human |
| `accepted_at` | `tga_extraction_results` | INTERNAL | yes | aggregate only | |
| Match score, agreed identifiers, reason | `match_candidates` | SENSITIVE | pseudonymous IDs only | never | provenance of a proposal |
| Pipeline stage, worker version, outcome | `pipeline_events` | INTERNAL | yes | aggregate only | 12-month retention |
| **Approval PDF (object bytes)** | private bucket | **HIGHLY_SENSITIVE** | **never** | **never** | presigned URL only (`12` §3) |
| Mailbox credential, scanner/OCR API key | Secrets Manager | **SECRET** | **never** | never | referenced by ARN only |
| Presigned URL | transient | **SECRET** | **never** | never | 5-minute TTL; never persisted, cached or logged |

`HIGHLY_SENSITIVE` carries a hard prohibition: never in an application log, an analytics pipeline or
error telemetry — not in a debug line, not in a stack trace, not in a request-body capture
(`12` §2, §5.2). Free-text reasons (correct/reject narratives) may contain clinical content even though
their column is `SENSITIVE`; they are captured in the audit record where the process requires them and
excluded from application logs and analytics (`12` §5.4).

## Residency

Documents, OCR text and extraction results are stored and processed only in `ap-southeast-2`
(`11` §8; `13` §1). Three external flows are not settled and no vendor is chosen:

| Flow | Vendor | Question | Owner | Status |
| --- | --- | --- | --- | --- |
| TGA correspondence channel | V-04 | Channel security statement, transport encryption, mailbox access and retention | Compliance/Auditor | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OCR / extraction service | V-07 | Residency, no-training commitment, deletion of documents and derived text, sub-processors | Security Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| Malware scanning | V-08 | Whether document content leaves Australia; quarantine design; deletion terms | Security Lead | **REQUIRES LEGAL/REGULATORY VALIDATION** |

Until those positions close, the OCR and managed-scanning paths must not receive production patient
data; an in-region alternative with no egress is the interim design (`11` §9; `16` §2).

## Audit events

Every event carries the standard envelope from `07` §2:
`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
reason, source_ip, request_id, correlation_id, prev_hash, hash`. `result` is
`SUCCESS | DENIED | FAILED | UNKNOWN`. **No event contains document text, OCR content, the subject, the
filename, or a patient identifier beyond the resource identifier** (`11` §11; `07` §7). Every event
carries the correlation identifier of the originating message.

**Registered actions** — present in `07` §1, usable as written:

| Action | Trigger | Key fields beyond the envelope |
| --- | --- | --- |
| `tga_document.ingest` | an attachment becomes a document row | `resource_id`, `source`, `content_hash`, `size_bytes` |
| `tga_document.extract` | extraction completes | `confidence`, `fields_extracted` |
| `tga_approval.match` | candidates proposed or resolved | `candidate_patient_ids`, `match_decision`, `confidence` |
| `tga_approval.verify` | reviewer decision recorded | `reviewer_id`, `decision`, `reason` |
| `tga_approval.create` | approval written from the inbox | `patient_id`, `category`, `dosage_form`, `source = INBOX_INGESTION` |
| `tga_approval.state_change` | every transition, including reversal | `from_state`, `to_state`, `reason` |
| `prescription.dispatch_blocked` | stage-12 re-evaluation still fails | `block_reason`, `approval_id` where known |
| `auth.step_up_failed` | verification or threshold change without fresh step-up | attempted `operation`, `resource_id` |
| `tenant.security_config_change` | confidence threshold changed (mapping to confirm — OPEN-4) | `changed_fields`, `step_up` |
| `audit.read` | a reviewer or auditor reads the trail | `query_filters`, `result_count` |

**Actions named in `11` §11 but absent from `07` §1 — REQUIRES REGISTRATION BEFORE USE.** `07` §1 states
that no module invents an action name outside its table without adding it there first. Until registered,
these must be emitted under a registered action or not at all:

| Unregistered name | Intended trigger | Owner | Status |
| --- | --- | --- | --- |
| `inbox.message.received` | a message arrives, with the authentication result | Security Lead | **REQUIRES REGISTRATION BEFORE USE** |
| `inbox.message.quarantined` | SPF/DKIM/DMARC failure or unknown sender | Security Lead | **REQUIRES REGISTRATION BEFORE USE** |
| `tga_document.validation_failed` | extension, MIME or magic-byte failure | Security Lead | **REQUIRES REGISTRATION BEFORE USE** |
| `tga_document.malware_detected` | a positive scan verdict | Security Lead | **REQUIRES REGISTRATION BEFORE USE** |
| `documents.read` | a presigned URL is issued and a document fetched | Security Lead | **REQUIRES REGISTRATION BEFORE USE** |

Adding a name to `07` §1 is a change to the audit contract and requires the same sign-off as a Gate 5
re-run.

## Retention

| Item | Retention | Source |
| --- | --- | --- |
| Original document and document metadata | Per `14-retention-and-deletion.md`, audit-linked; legal-hold check before expiry | `11` §5, §8 |
| Extraction result (candidates, confidence, provenance) | Same as the document | `11` §5 |
| Composite confidence and matching decision | Life of the approval record | `11` §5 |
| Reviewer identity and decision | Life of the approval record; event per audit retention | `11` §5 |
| `inbox_messages` source metadata | Per audit retention | `11` §5 |
| `pipeline_events` trace | **12 months** | `11` §5 |

Per-jurisdiction periods, and whether a legal hold suspends document expiry, are
**REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer.

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Retention period for inbox metadata, extraction results and pipeline traces | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether a legal hold suspends the document lifecycle expiry | Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Registration of the five action names above into `07` §1 | Security Lead | REQUIRES REGISTRATION BEFORE USE |
| Whether `tenant.security_config_change` covers a clinical-safety threshold change | CSO + Security Lead | OPEN |
| `sender_address` level: `12` §3 `CONFIDENTIAL` vs `04` §3.7 `SENSITIVE` (stricter applied) | Privacy Officer | OPEN |
| `field_name` level: `04` §3.7 `HEALTH_INFORMATION` vs `12` §3 `INTERNAL` (stricter applied) | Privacy Officer | OPEN |
