---
doc_id: OZ-FEAT-04-DESIGN
title: "FEAT-04 — TGA Approval Module: Technical Architecture & Database Design"
owner: CTO (interim: Ishu Rajput)
status: DRAFT — for review
last_reviewed: 2026-10-04
next_review: 2026-11-04
classification: RESTRICTED
feature_id: FEAT-04
phase: 02-phase-2-tga-approval-engine
gate: [2, 4]
source:
  - clinic-os-secure-by-design/04-database-erd.md §3.6, §8, §9
  - clinic-os-secure-by-design/05-tenant-isolation.md
  - clinic-os-secure-by-design/08-tga-approval-model.md
  - clinic-os-secure-by-design/21-technical-design.md
repo_docs:
  - 01-requirements.md
  - 04-threat-model.md
  - 05-data-and-audit.md
  - 06-test-plan.md
---

# Design

## Table: `tga_approval`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | generated server-side |
| `tenant_id` | uuid NOT NULL | set from session; RLS key |
| `patient_id` | uuid NOT NULL | FK; composite FK `(tenant_id, patient_id)` to `patients` |
| `category` | text NOT NULL | controlled list |
| `dosage_form` | text NOT NULL | controlled list |
| `approval_reference` | text NOT NULL | regulator reference as entered |
| `valid_from` | date NOT NULL | |
| `valid_to` | date NOT NULL | `CHECK (valid_to > valid_from)`; max 2 years (R3) |
| `status` | text NOT NULL | `CHECK IN ('pending_verification','active','expired','revoked')` |
| `source_document_id` | uuid NULL | private document store key |
| `created_by` | uuid NOT NULL | |
| `verified_by` | uuid NULL | `CHECK (verified_by IS NULL OR verified_by <> created_by)` |
| `verified_at` | timestamptz NULL | |
| `revoked_reason_code` | text NULL | code, not free text |
| `superseded_by_id` | uuid NULL | set when a new grant replaces this one |
| `created_at`, `updated_at` | timestamptz | |

Indexes: `(tenant_id, patient_id)`, `(tenant_id, status, valid_to)`.
**Constraint (R11):** partial `EXCLUDE USING gist` on
`(tenant_id =, patient_id =, category =, dosage_form =, daterange(valid_from, valid_to, '[)') && )`
`WHERE (status = 'active')`. Requires `btree_gist` — without it the migration fails, because the
equality operators are B-tree by default. See D-006 / OPEN-1.

## RLS
- `ENABLE` and `FORCE ROW LEVEL SECURITY` on `tga_approval`.
- Policy: `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid` for SELECT, INSERT, UPDATE.
  The `NULLIF` guard means an unset tenant matches nothing instead of raising a cast error.
- Tenant set with `SET LOCAL` inside each transaction, never per pooled connection.
- App role is not the table owner and has no `BYPASSRLS`.

## SQL Grants & Post-Verification Immutability

Database-level privileges and constraints prevent tampering, retrospective modification, or deletion of clinical regulatory records. The application connects as non-owner role `clinos_app`.

### 1. SQL Grants by Table
- **`tga_approval`**:
  - `GRANT SELECT, INSERT, UPDATE ON tga_approval TO clinos_app;`
  - `REVOKE DELETE, TRUNCATE ON tga_approval FROM clinos_app;`
  - Hard deletion is blocked at the database engine level (R13).
- **`tga_approval_events`** (Audit Trail):
  - `GRANT SELECT, INSERT ON tga_approval_events TO clinos_app;`
  - `REVOKE UPDATE, DELETE, TRUNCATE ON tga_approval_events FROM clinos_app;`
  - The audit log is strictly append-only by grant. Any attempt to modify or delete audit rows raises `42501 (insufficient_privilege)`.

### 2. Post-Verification Immutability Guard
Once an approval reaches `active` status:
- Core grain fields (`patient_id`, `category`, `dosage_form`), validity dates (`valid_from`, `valid_to`), and provenance (`approval_reference`, `source_document_id`, `verified_by`, `verified_at`) become **strictly immutable**.
- Only permitted lifecycle transitions (`active → revoked`, `active → expired`, `active → superseded`) are allowed, and each must be accompanied by an append-only event row in `tga_approval_events` in the same transaction.
- Extensions or dosage changes require a **new grant record** that supersedes the prior approval.
- Enforced in the database by a `BEFORE UPDATE` fail-closed trigger (`trg_tga_approval_lock_verified`) raising `VERIFIED_APPROVAL_IMMUTABLE` on unauthorized mutation.

## Endpoints

| Method and path | Permission | Notes |
| --- | --- | --- |
| `POST /api/v1/tga-approvals` | `tga_approval:create` | tenant from session; body has no tenant field |
| `GET /api/v1/patients/{patient_id}/tga-approvals` | `tga_approval:read` | list, cursor-paginated |
| `GET /api/v1/tga-approvals/{id}` | `tga_approval:read` | `404` on cross-tenant |
| `POST /api/v1/tga-approvals/{id}/verify` | `tga_approval:verify` | step-up; verifier differs from creator |
| `POST /api/v1/tga-approvals/{id}/revoke` | `tga_approval:revoke` | step-up; reason code required |
| `POST /api/v1/tga-approvals/match` | `tga_approval:read` | internal gate lookup; `POST` so no PHI in the URL |
| gate.check_active_approval(tenant, patient, category, form, service_date) | system | only caller is the dispatch gate |

No `DELETE` endpoint. Approvals are never hard-deleted by the app (R13; retention OPEN-6).

## Deny-by-default path for each request
1. Authenticate the session (deny if missing or expired).
2. Resolve tenant from the session; set it in the transaction.
3. Check permission for the role (deny if not granted).
4. Audit the decision, including refusals.
5. Validate the body against a strict schema (extra fields forbidden, so a `tenant_id` in the body is rejected).
6. Execute inside the RLS-scoped transaction.

## Expiry handling
A scheduled job marks `active` approvals `expired` when `valid_to` has passed. The gate does not trust
status alone: it also checks the window against `date_of_service`, so a late job cannot allow an
expired approval.

## Failure behaviour
Any error in the gate lookup is treated as **deny**. Errors return generic messages with a request ID;
no patient data in error bodies.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `btree_gist` availability on the target PostgreSQL build | Head of Platform | OPEN |
| `POST /tga-approvals/match` body shape (gate contract) | CTO + CSO | OPEN |
