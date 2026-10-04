---
doc_id: FEAT-DOC-03
title: Documents, design
owner: Head of Platform
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 21-technical-design, 12-data-classification
---

# Documents: design

## Table `documents`

| Column | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | uuid | PK, `DEFAULT gen_random_uuid()` | generated server-side, never client-supplied |
| `tenant_id` | uuid | NOT NULL, FK `tenants(id)` | set from session; RLS key (`04-database-erd.md` §3.9) |
| `patient_id` | uuid | NULL | composite FK `(tenant_id, patient_id)` to `patients`; null for tenant-level documents |
| `object_key` | text | NOT NULL, `CHECK (object_key LIKE 'tenants/' \|\| tenant_id \|\| '/documents/%')` | server-generated, immutable after insert |
| `original_filename` | text | NOT NULL | display only; sanitised; never used as a path |
| `mime_type` | text | NOT NULL, `CHECK (mime_type IN ('application/pdf','image/png','image/jpeg','image/tiff','application/vnd.openxmlformats-officedocument.wordprocessingml.document'))` | set from **magic bytes**, not the header |
| `size_bytes` | bigint | NOT NULL, `CHECK (size_bytes > 0 AND size_bytes <= 26214400)` | 25 MB cap (`11-tga-inbox-pipeline.md` §9) |
| `sha256` | bytea | NOT NULL | content hash recorded at ingest, verified on retrieval |
| `scan_state` | text | NOT NULL DEFAULT `'PENDING'`, `CHECK (scan_state IN ('PENDING','CLEAN','INFECTED','ERROR'))` | the visibility gate; `scan_engine_version` records the verdict's engine (`04-database-erd.md` §3.9) |
| `uploaded_by` | uuid | NOT NULL, FK `users(id)` | actor resolved from the session |
| `deleted_at`, `created_at` | timestamptz | `created_at` NOT NULL DEFAULT `now()` | soft delete; object lifecycle is separate |

`UNIQUE (tenant_id, id)` lets child tables carry a tenant-bound composite foreign key. Indexes:
`UNIQUE (tenant_id, object_key)`; `(tenant_id, patient_id, created_at DESC)`; `(tenant_id, scan_state)`.
No `DELETE` grant exists (R11).

## The object-key rule

The key is **generated server-side**, never supplied or edited by the client:

```
tenants/{tenant_id}/documents/{document_id}/v{n}/{sanitised_filename}
```

- `{sanitised_filename}` is the original name reduced to `[A-Za-z0-9._-]`, `..` and path separators
  removed, truncated to 100 characters; it is cosmetic, so the display name lives in
  `original_filename` (`11-tga-inbox-pipeline.md` §8).
- `v{n}` starts at `1` and increments on re-upload; bucket versioning means an overwrite never silently
  replaces a version.
- The bucket policy and the IAM policy condition on `tenants/{tenant_id}/`, and the presigner refuses
  a key without the caller's prefix (`05-tenant-isolation.md` §242). A client-supplied `object_key` is
  an unknown field and is rejected `422` (R2).

## The presigned-URL contract

| Rule | Statement | Source |
| --- | --- | --- |
| Authorisation first | A URL is minted **only after** an authorisation check on the document row: permission, tenant scope and treating relationship | `05-tenant-isolation.md` §243 |
| TTL | **Exactly 300 seconds (5 minutes)**, computed server-side from the server clock | `11-tga-inbox-pipeline.md` §8; `03-threat-model.md` §8; `05-tenant-isolation.md` §243 |
| Key binding | Bound to the exact `object_key`; the signature fails if the path or any signed header changes | `03-threat-model.md` §8 |
| No client key | The client never supplies or edits the key. The request carries a document id only | `05-tenant-isolation.md` §243 |
| Per request | Issued per request, never cached, never persisted, never emailed | `21-technical-design.md` §5 |
| Logged | Every issue — and every refusal — writes an audit event with actor, document id, purpose, request id | `21-technical-design.md` §5 |
| Delivery | `Content-Disposition: attachment`; served as `application/octet-stream` with `X-Content-Type-Options: nosniff` | `11-tga-inbox-pipeline.md` §8 |

The 15-minute figure is a credential TTL for access tokens (`03-threat-model.md` §172), not a document
TTL. A 15-minute document URL is a **rejected divergence**: it needs a decision record and a Gate 2/4
re-run before it may ship.

## Upload validation pipeline

Runs in order; the first failure stops the pipeline and writes an audit event.

| # | Stage | Rule | Failure result |
| --- | --- | --- | --- |
| 1 | Request size | 25 MB per file, 10 files per message, 100 MB per bulk request | `413` before any byte is stored |
| 2 | Extension allow-list | `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.docx`; double extensions rejected | `415 UNSUPPORTED_MEDIA_TYPE` |
| 3 | Declared MIME | `Content-Type` in the allow-list and consistent with the extension | `415`, quarantined |
| 4 | Magic bytes | First bytes match the declared format (`%PDF-`, PNG, JPEG, TIFF, ZIP/OOXML) | quarantined, never parsed |
| 5 | Key and store | Server builds the key; the object is written with `scan_state = 'PENDING'` | `500` and no object |
| 6 | Antivirus scan | Runs outside the request path; the verdict sets `CLEAN`/`INFECTED`/`ERROR` and the engine version | `INFECTED` quarantines and alerts the CSO |
| 7 | Visibility gate | Only `scan_state = 'CLEAN'` is reachable from the record or from a mint; `sha256` is recomputed on retrieval | `409 DOCUMENT_NOT_SCANNED`; a hash mismatch refuses and alerts |

Parsing runs isolated, with no egress and a wall-clock cap (`11 §9`); disarming PDFs whose fidelity is
clinically relied on is **REQUIRES LEGAL/REGULATORY VALIDATION**.

## Bucket configuration

| Concern | Setting |
| --- | --- |
| Access | Private bucket in `ap-southeast-2`; **Block Public Access** at account and bucket level; bucket policy denies any principal outside the application and pipeline roles; no public object, no public ACL, no unauthenticated read (`03-threat-model.md` §8; `21-technical-design.md` §5) |
| Encryption | SSE-KMS with a customer-managed key; envelope encryption with a data key per object; bucket policy denies non-TLS and non-KMS requests (`02-security-architecture.md` §5 control 7) |
| Versioning and lifecycle | Versioning enabled, so no version is silently replaced; transition to infrequent access at 90 days; expiry after the retention period, gated by a legal-hold check (`11-tga-inbox-pipeline.md` §8) |
| Quarantine | Separate bucket with a separate IAM boundary; a quarantined object is never served |
| Auditability | S3 server access logging plus a CloudTrail data event for object-level reads and writes |

## RLS and database privileges

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
CREATE POLICY pol_documents_tenant_isolation ON documents
  AS RESTRICTIVE FOR ALL TO clinos_app
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, INSERT, UPDATE ON documents TO clinos_app;  -- UPDATE for scan_state and deleted_at only
REVOKE DELETE, TRUNCATE ON documents FROM clinos_app;
GRANT SELECT, INSERT ON documents_events TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON documents_events FROM clinos_app;
```

- `NULLIF(...)` fails closed: an unset or empty setting becomes `NULL`, and no row matches.
- `FORCE ROW LEVEL SECURITY` closes the table-owner bypass. `clinos_app` is not the owner, holds no
  `BYPASSRLS`, and uses `SET LOCAL` inside the transaction only — never a session `SET` (`05 §3`).
- IAM mirrors the grant: `s3:GetObject` and `s3:PutObject` are scoped to
  `arn:...:documents/tenants/${aws:PrincipalTag/tenant_id}/*`; no `s3:DeleteObject` to the app role.

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `POST /api/v1/patients/{patient_id}/documents` | `document:create` | multipart; tenant from session; body has no key field |
| `GET /api/v1/patients/{patient_id}/documents` | `document:read` | cursor-paginated; `CLEAN` rows only |
| `GET /api/v1/documents/{id}` | `document:read` | metadata only; `404` on cross-tenant |
| `GET /api/v1/documents/{id}/url` | `document:read` | mints the 300 s URL; `409` unless `CLEAN` |
| `DELETE /api/v1/documents/{id}` | `document:delete` | soft delete; refused if referenced by an approval |
| scan result callback | system (signed event) | sets `scan_state`; never mints a URL |

## Deny-by-default request path

1. Authenticate the session; deny if missing or expired.
2. Resolve `tenant_id` from the session and `SET LOCAL` it in the transaction.
3. Check the permission for the role on this route; deny if not granted.
4. Load the document row **through RLS**; no row means `404`, never `403`.
5. For a mint: re-check the treating relationship and `scan_state = 'CLEAN'`.
6. Generate the key server-side; never read a key from the request.
7. Mint for 300 s, bound to that exact key.
8. Audit the decision — allow or deny — with the same envelope and the same fidelity.
9. Return; on any error, deny with a generic message plus a request id, and audit the failure.

## Failure behaviour

| Failure | Behaviour | Audited |
| --- | --- | --- |
| Scan service unavailable | `scan_state` stays `PENDING`; not visible; no mint | yes, `document.scan_failed` (`ERROR`) |
| Unknown `scan_state` value | row rejected by the `CHECK` constraint; no partial write | yes |
| Cross-tenant id | `404`, no body fields, no existence signal | yes, `DENIED` |
| URL used after expiry | S3 returns `403`; the attempt is recorded | yes |
| Hash mismatch on retrieval | retrieval refused, alert raised to the CSO | yes |
| Bucket write fails after the row insert | transaction rolls back; the orphan object is lifecycle-deleted | yes |

## Open items

| Item | Owner | Status |
| --- | --- | --- |
| `documents_events` is undefined in `04-database-erd.md`; the event store must be confirmed before the grant block is written. The table name also diverges (`11 §8` says `documents`, `12 §3` says `tga_documents`) | CTO + Head of Platform | OPEN — interim: `documents` |
| Malware-scan engine choice (ClamAV self-hosted vs managed) and its residency position | Head of Platform + Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
