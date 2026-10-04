---
doc_id: FEAT-AUD-01
title: Audit log, requirements
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 21-technical-design, 26-security-gates
source:
  - Privacy Act 1988 (Cth), APP 11
  - clinic-os-secure-by-design/07-audit-architecture.md §1, §2, §3, §4, §8, §10, §11
  - clinic-os-secure-by-design/21-technical-design.md §4
  - clinic-os-secure-by-design/04-database-erd.md §3.10, §9
  - clinic-os-secure-by-design/26-security-gates.md §3
  - clinic-os-secure-by-design/29-operations-and-observability.md §5
  - clinic-os-secure-by-design/12-data-classification.md §1, §3
  - clinic-os-secure-by-design/14-retention-and-deletion.md §3.5, §3.6
repo_docs:
  - 02-user-stories.md
  - 03-design.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
  - 07-definition-of-done.md
---

# Audit log, requirements

## Purpose

Make the question *"who looked at this record, who changed it, and why"* answerable with evidence that
outlives the application. The audit trail is a product feature and the platform's answer to an access
accounting request, not a log file (doc 07, opening).

## The append-only principle

**The audit outlives the application.** The trail is append-only at three independent levels — database
grants, RLS policy, and a single write path — because a grant prevents while a chain only detects, and
the immutable export outlives a compromised application server (doc 07 §3; doc 04 §9).

This feature owns the `audit_log` table, its grants, its hash chain and its export path. Every other
feature writes to it through the one writer.

## Requirements

| ID | Requirement | Testable acceptance | Source |
| --- | --- | --- | --- |
| **R1** | The application role holds exactly `SELECT, INSERT` on `audit_log` | The grant set read from `information_schema.role_table_grants` for grantee `clinos_app` equals `{SELECT, INSERT}`; no `UPDATE`, `DELETE` or `TRUNCATE` appears | doc 07 §3; doc 04 §9; `04 §9` — *enforcement is by grant, not by convention* |
| **R2** | An `UPDATE`, `DELETE` or `TRUNCATE` on `audit_log` as the application role is refused by the database | The statement raises `42501 insufficient_privilege`; the error is surfaced, alerted, never swallowed | doc 07 §3, §12 test 1; Gate 2 check |
| **R3** | One writer, inside the business transaction | The audit row and the domain change commit together; a rollback leaves no `audit_log` row and no outbox row; no module inserts directly | doc 07 §3 Level 3, §5, §12 test 4 |
| **R4** | A failed audit write fails the operation | A change that cannot be audited does not happen; the request returns `500`, the domain write rolls back, SEV2 alert raised | doc 21 §4; doc 07 §11; doc 29 §5 |
| **R5** | Every audited operation emits one event in the envelope | A coverage test asserts every action in the catalogue of doc 07 §1 is emitted at its trigger point | doc 07 §1, §2 |
| **R6** | The envelope is fixed and fully populated | `event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result, reason, source_ip, request_id, correlation_id, prev_hash, hash`; `result` ∈ `{SUCCESS, DENIED, FAILED, UNKNOWN}` | doc 07 §2; doc 21 §4 |
| **R7** | Denied, failed and unknown outcomes are audited with equal fidelity | `auth.login_failed`, `prescription.dispatch_blocked`, `prescription.dispatch_failed` and `audit.read` on an empty result each write an event | doc 07 §1, §12 test 7; README non-negotiable |
| **R8** | Tamper evidence by hash chain | `hash = SHA-256(canonical_json(event without hash) ‖ prev_hash)`; genesis `prev_hash` is 64 zeroes; altering or deleting one row is detected at that sequence number | doc 07 §10, §12 tests 8–9 |
| **R9** | The chain is verified continuously and in full | Continuous verification over the last 24 h every 15 min alerts on a break; a scheduled full-chain job writes a signed verification report to the immutable store | doc 07 §10 |
| **R10** | Immutable export that outlives the application | Outbox row in the same transaction → SQS → S3 Object Lock `COMPLIANCE` mode in `ap-southeast-2`, versioned; writer role write-only; bucket policy denies `s3:DeleteObject` to all but the audited break-glass role | doc 07 §4; doc 21 §4; doc 13 |
| **R11** | Nothing clinical, secret or full-body enters a payload | Per-action metadata allow-list enforced by schema before insert; an unlisted key throws `AUDIT_PAYLOAD_REJECTED` and the request fails | doc 07 §7, §11, §12 test 10 |
| **R12** | Tenant-scoped, filtered, paginated read; the read is itself audited | Keyset on `(timestamp, event_id)`; default 50 max 200; unbounded scan `422`; range max 90 days; cross-tenant id `404`; every call writes `audit.read` | doc 07 §8, §12 tests 3, 7, 13 |
| **R13** | Retention is partition-level expiry, and a legal hold blocks it | No row-level delete path exists; a partition drop for a partition under legal hold is refused; expiry is the only removal mechanism | doc 07 §9, §12 test 14; doc 14 §3.5, §3.6 |
| **R14** | `audit_log` is tenant-scoped under RLS with the fail-closed guard | `ENABLE` and `FORCE ROW LEVEL SECURITY`; policies use `NULLIF(current_setting('app.tenant_id', true), '')::uuid`; no `UPDATE` or `DELETE` policy exists; an unset tenant matches no rows | doc 07 §3 Level 2; doc 05 §5.1 |
| **R15** | The application role is not the table owner and has no `BYPASSRLS` | `pg_class.relowner` for `audit_log` is the migrator role; `rolbypassrls` is false for the app role | Gate 2 check; doc 05 §4 |

## Out of scope

- Clinical, TGA-approval and prescription domain tables — this feature owns the trail, not the records.
- Retention periods and jurisdiction selection (R13 mechanism only; period is OPEN, and the obligation
  itself is *Privacy Act 1988* (Cth) APP 11 plus state and territory health records legislation).
- Writing the audit-of-read UI; `/api/v1/audit/*` is the surface this feature owns.
- Frontend rendering of the trail — reports feature 14 consumes the read API.
- Bulk DSAR export workflow — feature 14.

## Open items

| # | Item | Owner | Status |
| --- | --- | --- | --- |
| OPEN-1 | Retention period per event class and jurisdiction. Working assumption only: 7 years for health-record-linked events, 12 months for authentication events | Head of Legal and Compliance | **REQUIRES LEGAL/REGULATORY VALIDATION** |
| OPEN-2 | Envelope field-form conflicts across the source: `event_id` ULID vs `uuid PK`; `timestamp` PK component vs not; `request_id` NOT NULL vs `text NOT NULL` in doc 21; `reason` `HIGHLY_SENSITIVE` in doc 04 §3.10 vs `SENSITIVE` in doc 12 §3 | Security Lead | OPEN |
| OPEN-3 | Action-name convention: doc 07 §1 uses lowercase dotted (`patient.read`), doc 04 §3.10 shows `PATIENT_READ`. This feature adopts doc 07's form | Security Lead | OPEN — see 05-data-and-audit |
| OPEN-4 | Whether the `POST /api/v1/audit/export` bundle path is owned here or by feature 14 | Compliance Lead | OPEN |
| OPEN-5 | Break-glass procedure for platform staff to read a tenant trail, and who approves it | Security Lead | OPEN |
| OPEN-6 | Rate-limit constant for the audit read API (60/min per actor) against the repo's tiering | Head of Platform | OPEN |
| OPEN-7 | `tenant_id IS NULL` platform events: readable by the readonly audit role, and how a platform event reaches `clinos_app` under RLS | Security Lead + CTO | OPEN |
