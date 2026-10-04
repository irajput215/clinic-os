---
doc_id: FEAT-AUD-03
title: Audit log, design
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 07-audit-architecture, 21-technical-design, 26-security-gates
source:
  - clinic-os-secure-by-design/07-audit-architecture.md §2, §3, §4, §5, §6, §8, §9, §10, §11
  - clinic-os-secure-by-design/21-technical-design.md §4
  - clinic-os-secure-by-design/04-database-erd.md §3.10, §9
  - clinic-os-secure-by-design/05-tenant-isolation.md §4, §5
  - clinic-os-secure-by-design/26-security-gates.md §3
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Table: `audit_log` (append-only, partitioned monthly on `timestamp`)

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `event_id` | uuid | no | PK with `timestamp`; assigned by the writer, never by the caller. Doc 07 §2 renders it as a ULID; doc 04 §3.10 types it `uuid` — OPEN-2 |
| `timestamp` | timestamptz | no | server clock only, stored UTC, rendered `Australia/Sydney`; partition key |
| `tenant_id` | uuid | yes | from request context, never the body. NULL only for platform-level events with no tenant |
| `actor_id` | uuid or `SYSTEM` | yes | null for system and anonymous failures; `SYSTEM` for jobs with the job name in `reason` |
| `actor_role` | text | yes | the role held **at decision time**, not the role held later |
| `action` | text | no | closed vocabulary, lowercase dotted form (doc 07 §1); no invented names |
| `resource_type` | text | no | `PATIENT, CLINICAL_RECORD, PRESCRIPTION, TGA_APPROVAL, TGA_DOCUMENT, USER, TENANT, SESSION, AUDIT, REPORT, INTEGRATION, EXPORT` |
| `resource_id` | uuid | yes | identifier of the affected record |
| `result` | text | no | `CHECK IN ('SUCCESS','DENIED','FAILED','UNKNOWN')`; `UNKNOWN` is a provider timeout or an unresolved outcome |
| `reason` | text | yes | a controlled code, not free text, unless the actor typed a justification |
| `source_ip` | inet | yes | truncated to `/24` (v4) and `/48` (v6) in the export stream |
| `request_id`, `correlation_id` | text | `request_id` no | per request and per business intent; joins the log line to the event and follows it across queues and providers |
| `prev_hash` | bytea | yes | `hash` of the previous event in the tenant chain; genesis is 64 zeroes |
| `hash` | bytea | no | SHA-256 over the canonical serialisation of this event with `prev_hash` |

PK `(event_id, timestamp)`. Indexes: `(tenant_id, timestamp DESC)`, `(tenant_id, actor_id, timestamp
DESC)`, `(tenant_id, resource_type, resource_id, timestamp DESC)`, `(tenant_id, action, timestamp
DESC)`. **No foreign keys** — an audit row must survive the deletion of the resource it describes.
Partitioned monthly by range on `timestamp`, with a default partition that alerts.

## RLS

- `ENABLE` and `FORCE ROW LEVEL SECURITY`; the policy applies to the owner too.
- Two policies only, and no more: `audit_log_insert` `WITH CHECK` and `audit_log_select` `USING`, both
  `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`. **No `UPDATE` policy and no
  `DELETE` policy exists**, so those statements affect zero rows even if a grant is granted in error.
- Tenant set with `SET LOCAL` inside each transaction, never per pooled connection; each worker, cron job
  or consumer opens its own transaction and sets its own context.
- `tenant_id IS NULL` platform events reach `clinos_readonly_audit` only, never `clinos_app` on a
  tenant-scoped read path (doc 05 §5.3). OPEN-7.

## Database privileges — the centrepiece

The application connects as `clinos_app`, a dedicated **non-owner** role. Enforcement is by grant, not by
convention: *"a convention is bypassed by a determined developer; a missing privilege is not"*
(`04-database-erd.md` §9).

| Role | Purpose | Grants on `audit_log` | RLS |
| --- | --- | --- | --- |
| `clinos_app` | API and worker runtime — every request | **`SELECT, INSERT` only.** `REVOKE UPDATE, DELETE, TRUNCATE` | Non-owner, subject to RLS; no `BYPASSRLS` |
| `clinos_readonly_audit` | Compliance and auditor reads, evidence export | `SELECT` only | Subject to RLS |
| `clinos_migrator` | Owns the schema, runs migrations | DDL; owns the table; partition management only | `FORCE ROW LEVEL SECURITY` still applies |
| `clinos_retention` | Retention job identity | Partition drop only, after legal-hold check | Subject to RLS |

```sql
GRANT SELECT, INSERT ON audit_log TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
-- a CI test asserts the resulting set after every migration: expected exactly SELECT and INSERT
```

An `UPDATE` or `DELETE` against `audit_log` through the application role raises
`42501 insufficient_privilege` (Gate 2). A repository lint rule fails the build on any `UPDATE audit_log`
or `DELETE FROM audit_log` string in the source tree. The grant listing, not the code, is the evidence.

## Write path

One writer. `core/audit.py` is the only code that inserts into `audit_log`; no controller inserts
directly. The writer reads the last event in the tenant chain under a row lock to compute `prev_hash`
and inserts **inside the caller's transaction** — domain change, audit event and outbox row commit
together or not at all.

```sql
BEGIN;
  SET LOCAL app.tenant_id = '...';
  UPDATE prescriptions SET state = 'SIGNED', signed_at = now() WHERE id = $1 AND state = 'DRAFT';
  INSERT INTO audit_log (...) VALUES (...);   -- computed prev_hash + hash
  INSERT INTO audit_outbox (event_id, payload) VALUES (...);
COMMIT;
```

**A failed audit write fails the operation** — a change that cannot be audited must not happen (doc 07 §11).

## Hash chain

`hash = SHA-256(canonical_json(event_without_hash) ‖ prev_hash)`, where `canonical_json` sorts keys, uses
UTF-8 and omits `hash`. The first event in a tenant chain uses a genesis `prev_hash` of 64 zeroes.
Verification runs continuously over the last 24 h every 15 min and in full per partition as a scheduled
job writing a signed report. A sequence gap, a recomputed-hash mismatch or a `prev_hash` mismatch is a
break → P1 incident (doc 18).

## Immutable export path

Outbox row in the same transaction → SQS queue (KMS-encrypted) → S3 Object Lock bucket in
`ap-southeast-2`, `COMPLIANCE` mode, versioned. The stream writer holds a **write-only** role and
verifies the chain segment before upload; a break stops the upload, alerts and leaves events in the
outbox. A local bounded buffer absorbs a stream outage; a periodic verifier compares a hash chain over the
exported sequence. The bucket policy denies `s3:DeleteObject` and `s3:PutBucketObjectLockConfiguration` to
every principal except the audited break-glass security role.

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/v1/audit` | `audit:read` | keyset on `(timestamp, event_id)`; default 50, max 200; filters `action`, `actor_id`, `resource_type`, `resource_id`, `result`, `from`, `to`; range max 90 days; unbounded scan `422`; rate limit 60/min per actor; `audit.read` written on every call including an empty result |
| `GET /api/v1/audit/{event_id}` | `audit:read` | the envelope only; cross-tenant id returns `404` |
| `POST /api/v1/audit/export` | `audit:read` | range-bounded CSV or JSONL bundle to a tenant-scoped prefix, short-lived presigned URL, audited as `audit.read` with `reason = EXPORT`; owner OPEN-4 |

`audit:read` is granted to Practice Owner, Administrator and Compliance/Auditor only. Platform staff
cannot read a tenant's trail without a time-boxed, notified, audited break-glass grant.

## Deny-by-default request path

1. Authenticate the session (deny if missing or expired).
2. Resolve the tenant from the session; `SET LOCAL` it in the transaction.
3. Check `audit:read` for the role (deny if not granted).
4. Validate filters strictly: unknown fields rejected, unbounded scan refused `422`.
5. Audit the decision, including refusals; read inside the RLS transaction; return the envelope only.

## Failure behaviour

| Failure | Behaviour |
| --- | --- |
| Audit write fails, including a non-allow-listed payload key | Domain write rolls back, `500` with a request ID, SEV2 alert; the operation did not happen |
| Stream/outbox outage | Local bounded buffer absorbs it and alerts; no committed event is silently unstreamed |
| Hash-chain break | Upload stops, P1 incident, events stay in the outbox for investigation |
| Unset tenant setting; cross-tenant id | Matches no rows, never all rows; `404`, never `403` — a `403` confirms existence |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| Partition granularity at expected audit volume | CTO | OPEN |
| Ownership of the export bundle path (feature 14?) and of `audit_outbox` | Compliance Lead + CTO | OPEN |
| Envelope type conflicts: `event_id` ULID vs `uuid`, `prev_hash`/`hash` bytea vs hex string | Security Lead | OPEN |
