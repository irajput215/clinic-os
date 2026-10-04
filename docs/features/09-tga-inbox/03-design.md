---
doc_id: OZ-FEAT-09-DESIGN
title: "TGA inbox — design"
owner: CTO + Clinical Safety Officer
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-09
phase: 02-phase-2-tga-approval-engine
gate: [5]
source:
  - clinic-os-secure-by-design/11-tga-inbox-pipeline.md
  - clinic-os-secure-by-design/04-database-erd.md §3.7, §3.9, §8, §9
  - clinic-os-secure-by-design/21-technical-design.md §9
  - clinic-os-secure-by-design/26-security-gates.md §6
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

PostgreSQL 16; every `id` is `uuid DEFAULT gen_random_uuid()`. Source: `04-database-erd.md` §3.7.

## Inbox tables

| Table | Columns (type — constraint) |
| --- | --- |
| `tga_inbox_messages` | `id` uuid PK · `tenant_id` uuid NOT NULL FK `tenants(id)` — RLS key; one mailbox → exactly one tenant · `provider_message_id` text NOT NULL, `UNIQUE (tenant_id, provider_message_id)` dedupes redelivery · `from_address`, `to_address` text NOT NULL · `subject` text NOT NULL — `HIGHLY_SENSITIVE`, never logged · `received_at` timestamptz NOT NULL — the 2-minute clock starts here · `spf_result`, `dkim_result`, `dmarc_result` text NULL — recorded and displayed at verification · `processing_state` text NOT NULL, `CHECK IN ('RECEIVED','EXTRACTING','EXTRACTED','FAILED','VERIFIED','REJECTED')` · `raw_object_key` text NOT NULL — server-generated, tenant-prefixed · `created_at` timestamptz NOT NULL DEFAULT `now()` |
| `tga_inbox_attachments` | `id` uuid PK · `tenant_id` uuid NOT NULL FK `tenants(id)` · `message_id` uuid NOT NULL — composite FK `(tenant_id, message_id)` → `tga_inbox_messages` · `object_key` text NOT NULL — server-generated; the original filename is **never** the key · `original_filename` text NOT NULL — `HIGHLY_SENSITIVE`, sanitised for display only · `content_type` text NOT NULL — from magic bytes, not the header · `size_bytes` bigint NOT NULL, `CHECK (size_bytes <= 26214400)` (25 MB) · `sha256` bytea NOT NULL — integrity and dedupe · `scan_state` text NOT NULL, `CHECK IN ('PENDING','CLEAN','INFECTED','ERROR')` · `scanned_at`, `created_at` timestamptz |
| `tga_extraction_results` | `id` uuid PK · `tenant_id` uuid NOT NULL FK `tenants(id)` · `attachment_id` uuid NOT NULL — composite FK `(tenant_id, attachment_id)` · `extractor_version` text NOT NULL — a regression is traceable · `field_name` text NOT NULL, `CHECK IN ('PATIENT_NAME','TGA_CATEGORY','DOSAGE_FORM','VALID_FROM','VALID_TO')` · `raw_value` text NULL — as extracted, **immutable after the extractor writes it** · `confidence` numeric(4,3) NULL, `CHECK (confidence BETWEEN 0 AND 1)` · `page_number` integer NULL, `region` jsonb NULL — **proposed extension** required by `21` §9, absent from `04` §3.7 (OPEN-3) · `accepted_value` text NULL until a human accepts · `accepted_by` uuid NULL FK `users(id)`, `accepted_at` timestamptz NULL |

- `tga_inbox_messages`: index `(tenant_id, processing_state, received_at)`.
- `tga_inbox_attachments`: index `(tenant_id, message_id)`; not visible to any user until `scan_state = 'CLEAN'`.
- `tga_extraction_results`: `UNIQUE (tenant_id, attachment_id, field_name, extractor_version)`, index `(tenant_id, attachment_id)`; the extractor role has `INSERT` here and **no access to `tga_approvals`**.
- `match_candidates` / `pipeline_events`: named in `11` §5, unspecified in `04` — proposed columns and 12-month trace retention in OPEN-4.

## The ordered pipeline

| # | Stage | Control | On failure |
| ---: | --- | --- | --- |
| 1 | Secure inbox | SPF/DKIM/DMARC; per-tenant sender allow-list plus unknown-sender quarantine; service-role-only mailbox access | Quarantine; no attachment extracted |
| 2 | Attachment extraction | Allow-listed types; ≤ 25 MB; ≤ 10 per message; double extensions rejected | Refused attachment recorded; message partially processed |
| 3 | Sender/attachment validation | Declared type vs extension vs magic bytes must agree | Quarantine + alert; **never parsed** |
| 4 | MIME and size check | `Content-Type` allow-list and consistency; size cap enforced before storage | `415` / `413`; no object written |
| 5 | Malware scan | Scan in a quarantine bucket with a separate IAM boundary, before reachability | Quarantine, CSO notified, pipeline stopped, incident raised |
| 6 | Private object storage | `ap-southeast-2`, versioning, SSE-KMS, server-generated key, hash recorded at ingest | Hash mismatch on retrieval blocks retrieval + alert |
| 7 | PDF / OCR | Text layer first; OCR only where none exists; isolated worker, no egress; encrypted files not cracked | Manual review with `ENCRYPTED` / `PASSWORD_PROTECTED` |
| 8 | Field and number extraction | Configured pattern set **plus** an independent pass; never a single method; per-field confidence and page/region | No candidate above the floor → manual review |
| 9 | Patient and grain matching | Deterministic strong identifiers first, then configured fuzzy; candidates only; within one tenant | No candidate above threshold → manual-resolution queue |
| 10 | Confidence score | Weighted composite of field and match confidence against the policy threshold | Below threshold stays `PENDING` in the human queue |
| 11 | **Human verification** | Document beside fields, per-field confidence, candidates with reasons; accept / correct / reject / defer | — |
| 12 | Approval record | Written at the FEAT-08 grain with `source = INBOX_INGESTION`; duplicate grain enters supersede | Duplicate refused |
| 13 | Audit | One event per stage, doc 07 envelope, same-transaction write | Audit write failure stops the pipeline |
| 14 | Workflow update | A blocked prescription at the grain is **re-evaluated**; the pipeline never dispatches | Still-failing re-evaluation leaves it `BLOCKED` |

## Invariants

- **No automated step writes clinical state; no path reaches `ACTIVE` without a recorded human decision.** The extractor role cannot write `tga_approvals`; the verify endpoint is the only writer of `ACTIVE` (`11` §3 r3; `21` §9; `26` §6).
- **Matching never crosses tenants and never merges patients.** A candidate is a proposal, never a write; a national identifier is not a tenant-crossing key (`11` §7).
- **Filename, `Content-Type`, extension and OCR text are all untrusted input.** The object key is generated server-side; the filename is sanitised for display and never a path; OCR output is never executed, never used to build a query, never trusted to select a patient (`11` §9).

## Confidence threshold — a clinical safety parameter

`tenant_policy.tga_inbox_confidence_threshold` (table unspecified in `04` — OPEN-2), writable only by `tenant:configure` with step-up, change audited. Defaults are **recommendations requiring CSO sign-off, not constants**: composite `0.95`, per-mandatory-field floor `0.80`, match `0.90`, auto-create **not enabled by default**. Below the composite the record goes to human verification; below a field floor it routes regardless of the composite. Whether a regulator prescribes a threshold is **REQUIRES LEGAL/REGULATORY VALIDATION** (`11` §4).

## Privileges — append-only by grant

```sql
GRANT SELECT, INSERT ON tga_inbox_messages, tga_inbox_attachments,
     match_candidates, pipeline_events TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON tga_inbox_messages, tga_inbox_attachments,
     match_candidates, pipeline_events FROM clinos_app;
GRANT SELECT, INSERT ON tga_extraction_results TO clinos_app;                 -- 04 §9
GRANT UPDATE (accepted_value, accepted_by, accepted_at) ON tga_extraction_results TO clinos_app;
REVOKE DELETE, TRUNCATE ON tga_extraction_results FROM clinos_app;
GRANT INSERT, SELECT ON tga_extraction_results TO clinos_extractor;           -- extractor role
REVOKE ALL ON tga_approvals FROM clinos_extractor;
```

The app role is not the table owner and has no `BYPASSRLS`; the extractor role is separate.

## RLS

`ENABLE` and `FORCE ROW LEVEL SECURITY` on every tenant-scoped inbox table, `AS RESTRICTIVE FOR ALL TO clinos_app`, `USING` and `WITH CHECK` both `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. The `NULLIF` guard fails closed: a lost context matches nothing, not everything. Context is set with `SET LOCAL` inside the transaction only; plain `SET` is prohibited (`04` §8).

## Queue and reprocess state machine

```
RECEIVED -> EXTRACTING -> EXTRACTED -> VERIFIED -> tga_approval.create (PENDING)
                    |            \--> REJECTED  (reason required)
                    \--> FAILED  (reason) --reprocess--> EXTRACTING   (attempt n+1)
```

`processing_state` uses the ERD vocabulary above. Review-queue item states `REVIEW_REQUIRED`, `DEFERRED` and the lease fields (`claimed_by`, `claimed_at`, `lease_expires_at`) are a **design proposal** (not in `04` — OPEN-4): oldest-first, > 4 h CSO alert, a second concurrent claim returns `409 Conflict`. Reprocess is idempotent: a new attempt keyed by `extractor_version`, never a rewrite of a prior result (`11` §6, §10).

## Endpoints

| Method and path | Permission | Notes | Source |
| --- | --- | --- | --- |
| `POST /api/v1/tga-inbox/messages` | mailbox service role | ingest callback, not a user route; tenant from the mailbox identity | `03` §7 |
| `GET /api/v1/tga-inbox/messages` | `tga_inbox:read` | review queue, oldest first, cursor-paginated | `11` §6 |
| `GET /api/v1/tga-inbox/{id}` | `tga_inbox:read` | fields, confidence, provenance, candidates with reasons; `404` cross-tenant | `11` §6 |
| `GET /api/v1/documents/{id}/url` | `document:read` | 300 s presigned URL; `409` unless `CLEAN` (FEAT-07 route) | `11` §8 |
| `POST /api/v1/tga-inbox/{id}/verify` | `tga_inbox:verify` | step-up; the **only** writer of `ACTIVE`; approval + event in one transaction | `03` §7 |
| `POST /api/v1/tga-inbox/{id}/reject` | `tga_inbox:verify` | reason required | `03` §7 |
| `POST /api/v1/tga-inbox/{id}/defer` | `tga_inbox:verify` | returns the item to the queue | `11` §6 |
| `POST /api/v1/tga-inbox/{id}/reprocess` | `tga_inbox:reprocess` (OPEN) | re-runs from a named stage; idempotent | `11` §10 |

No route accepts a `tenant_id`, `state`, `patient_id`, `score` or `accepted_value` from the client (strict Pydantic v2, `extra = "forbid"`).

## Deny-by-default request path

1. Authenticate the session (deny if missing or expired).
2. Resolve the tenant from the session; `SET LOCAL app.tenant_id` inside the transaction.
3. Check the permission for the role (deny if not granted).
4. Apply the care-relationship rule for the reviewer.
5. Audit the decision, **including refusals**, before returning it.
6. Validate the body against a strict schema (unknown fields rejected).
7. Execute inside the RLS-scoped transaction; state transitions are server-managed.
8. Return `404`, never `403`, across a tenant boundary.

## Failure behaviour

Any error resolving tenant, authorisation or a document's scan state is **deny**. Errors carry a request
ID and no patient data, no OCR text, no stack trace. A quarantined or unclean object is never served. An
audit write failure aborts the transaction (`11` §8, §10; `03` §13).

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| `tenant_policy` table unspecified in `04` (OPEN-2) | Head of Platform | OPEN |
| Page/region provenance columns absent from `04` §3.7 (OPEN-3) | CTO + CSO | OPEN |
| `match_candidates`, `pipeline_events` and queue-item states unspecified in `04` (OPEN-4) | CTO | OPEN |
| Object key convention conflict between `11` §8 and `04` §3.9 (OPEN-6) | Security Lead | OPEN |
| `tga_inbox:reprocess` permission is not in the RBAC source | Security Lead | OPEN |
| Mailbox provider residency and processing position (V-04) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
