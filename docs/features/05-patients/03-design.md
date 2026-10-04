---
doc_id: FEAT-PAT-03
title: Patients, design
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Design

## Table: `patients`
Columns are exactly those in `04-database-erd.md` §3.4. Identifiers are **inline columns**; the
`patient_identifiers` table named in `20-product-requirements.md` §3 is **not** in the ERD and is not
created here.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | no | PK, `gen_random_uuid()` |
| `tenant_id` | uuid | no | FK `tenants(id)`; RLS key |
| `given_name`, `family_name` | text | no | plaintext under RLS (search and sort keys) |
| `preferred_name` | text | yes | |
| `date_of_birth` | date | no | plaintext under RLS (search and sort key) |
| `sex_at_birth` | text | yes | closed-set check constraint |
| `gender_identity` | text | yes | separate from sex at birth |
| `medicare_number` | bytea | yes | field-level encrypted |
| `medicare_blind_index` | bytea | yes | keyed HMAC, exact match only |
| `ihi` | bytea | yes | field-level encrypted |
| `ihi_blind_index` | bytea | yes | keyed HMAC, exact match only |
| `address_line`, `suburb`, `state`, `postcode` | text | yes | |
| `phone`, `email` | text | yes | |
| `deceased_at` | timestamptz | yes | blocks certain operations |
| `merged_into_patient_id` | uuid | yes | self-FK; a merge never hard-deletes |
| `deleted_at` | timestamptz | yes | soft delete, retained for the retention period |
| `created_at`, `updated_at` | timestamptz | no | |

PK `(id)`; `UNIQUE (tenant_id, id)` so child tables can use tenant-bound composite FKs. No constraint
requires an identifier: Medicare and IHI may both be null.

## Field-level encryption decision (`02-security-architecture.md` §5.1)
The decision is reproduced, with its four documented consequences:

| Field | Decision | Reason |
|---|---|---|
| `medicare_number` | Encrypt with a separate CMK; keyed blind index for exact match | Large value space, so equality leakage is acceptable; exact lookup is required for claiming |
| `ihi` | Encrypt; keyed blind index for exact match | Same reasoning; a national identifier and highly sensitive |
| `family_name`, `given_name`, `date_of_birth` | **Plaintext under RLS** | The primary search and sort keys; encrypting them breaks patient search, which is itself a clinical safety control |

Consequences, as documented:
1. **Search limitation** — encrypted columns cannot be searched; a search needing the identifier accepts
   the blind-index value and supports **exact match only**, never prefix or fuzzy match.
2. **Blind-index equality leakage** — equality is observable to anyone with database read access and the
   index key. Accepted for high-entropy identifiers; rejected for low-entropy values such as date of
   birth or postcode.
3. **Key rotation** — rotating the CMK does not re-encrypt row data; re-keying requires a migration that
   reads, decrypts and rewrites each row **in batches**. A planned artefact, not an emergency procedure.
4. **Deterministic and order-revealing encryption are rejected** for patient data — they leak equality
   and order respectively.

## Blind index
`medicare_blind_index` and `ihi_blind_index` are keyed HMACs. Lookup is `WHERE tenant_id = $1 AND
medicare_blind_index = $2`; the plaintext value never reaches the query. Key custody and rotation for the
blind-index key are an open item (`04-database-erd.md` open item 5).

## Indexes (tenant_id leading)
- `idx_patients_tenant_family_name (tenant_id, family_name, given_name)`
- `idx_patients_tenant_dob (tenant_id, date_of_birth)`
- `idx_patients_tenant_medicare_blind_index (tenant_id, medicare_blind_index)`
- `idx_patients_tenant_ihi_blind_index (tenant_id, ihi_blind_index)`
- `idx_patients_tenant_active (tenant_id) WHERE deleted_at IS NULL`

## RLS (`04-database-erd.md` §8; `05-tenant-isolation.md` §5.1)
```sql
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;   -- applies to the owner too

CREATE POLICY pol_patients_tenant_isolation ON patients
  AS RESTRICTIVE FOR ALL TO clinos_app
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```
`NULLIF(...)` fails closed: an unset or empty setting becomes `NULL`, and `tenant_id = NULL` matches no
row. Tenant is set with `SET LOCAL` inside the transaction, never per pooled connection.

## Database privileges (enforcement, not convention)
```sql
GRANT SELECT, INSERT, UPDATE ON patients TO clinos_app;
REVOKE DELETE, TRUNCATE ON patients FROM clinos_app;   -- the no-hard-delete rule, enforced by grant
-- The ERD permits hard delete only via the retention job identity:
-- GRANT DELETE ON patients TO clinos_retention;       -- approved purge jobs only
```
Grant inspection runs after every migration and fails if `DELETE` appears for `clinos_app`
(`04-database-erd.md` §4.7, §9; `05-tenant-isolation.md` §4).

## Treating-relationship rule
`patient:read` and `clinical_record:read` are refused unless the actor holds an **active care
relationship** for that patient in the same tenant (`06-authentication-rbac.md` §10). It is never
inferred from clinic membership and never widens to the tenant.
> **Blocked dependency.** `hasActiveCareRelationship` reads `care_relationships(tenant_id,
> practitioner_id, patient_id, clinic_id, active_from, active_to, source)`, which has **no ERD table
> definition and no named owner** (`06-authentication-rbac.md` §11 open item 5). Not designed here; the
> rule cannot be fully evidenced until the table is specified.

## Endpoints

| Method and path | Permission | Notes |
|---|---|---|
| `POST /api/v1/patients` | `patient:create` | tenant from session; body has no `tenant_id` |
| `GET /api/v1/patients` | `patient:read` | cursor-paginated, treating-relationship filtered |
| `POST /api/v1/patients/search` | `patient:read` | **POST with a body**; source names `GET /patients/search?q=` |
| `GET /api/v1/patients/{id}` | `patient:read` | `404` on cross-tenant |
| `PATCH /api/v1/patients/{id}` | `patient:update` | unknown fields rejected |
| `GET /api/v1/patients/{id}/duplicates` | `patient:read` | exact-match candidates only |
| `POST /api/v1/patients/{id}/merge` | `patient:merge` | step-up; body names the losing record and a reason |
| `POST /api/v1/patients/{id}/merge/reverse` | `patient:merge` | step-up; designed reversal |

No `DELETE` endpoint. A patient is never hard-deleted by the application.

## Deny-by-default request path
1. Authenticate the session (deny if missing or expired).
2. Resolve tenant from the session; open the transaction and `SET LOCAL app.tenant_id`.
3. Check permission for the role (deny if not held).
4. Evaluate the treating-relationship rule for the resource (deny if no active relationship).
5. Audit the decision, including every refusal, with the equal-fidelity rule.
6. Validate the body against a strict Pydantic v2 schema (extra fields forbidden, so `tenant_id` is
   rejected).
7. Execute inside the RLS-scoped transaction; write the audit event in the same transaction.
8. Serialise through a declared response model with `HIGHLY_SENSITIVE` fields masked.

## Failure behaviour
Any failure to resolve tenant, permission or relationship denies — never a default allow and never a
partially scoped query. Errors return the standard envelope with a `request_id`; error bodies and stack
traces carry no patient data. A failed audit write rolls back the change (fail closed).

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `care_relationships` undefined in the ERD — the relationship control is unevidenced | Clinical Safety Officer + Engineering Lead | **OPEN — blocked** |
| `patient:merge` appears in `20-product-requirements.md` §3 but not in the fixed permission list in `04-database-erd.md` §3.3 | CTO + Head of Product | OPEN |
| Blind-index key custody and rotation | Security Lead | OPEN |
| Whether a merge must be reversible after a clinical event, and for how long | Clinical Safety Officer | OPEN |
