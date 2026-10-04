---
doc_id: FEAT-CLIN-03
title: Clinical records, design
owner: Clinical Safety Officer
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 04-database-erd, 12-data-classification, 14-retention-and-deletion
---

# Design

Stack: Python 3.14 / FastAPI / Pydantic v2 / SQLModel / psycopg3 / Alembic / PostgreSQL 16. Schema
contract: `04-database-erd.md` §3.5. The source has no `clinical_notes` table and no encounter table;
neither is introduced. Classification per column is in [05-data-and-audit.md](05-data-and-audit.md).

## Schema

| Table | Column | Type | Null | Constraint / notes |
| --- | --- | --- | --- | --- |
| `clinical_records` | `id` | uuid | no | PK, server-generated |
| | `tenant_id` | uuid | no | FK `tenants(id)`; RLS key |
| | `patient_id` | uuid | no | composite FK `(tenant_id, patient_id)` to `patients` |
| | `record_type` | text | no | `CHECK IN ('NOTE','OBSERVATION','HISTORY','ADDENDUM','RESULT')` |
| | `author_id` | uuid | no | FK `users(id)`; attribution is the point |
| | `current_version` | integer | no | `DEFAULT 1`; authoritative pointer to the highest version |
| | `signed_at` | timestamptz | yes | set on sign; content can then only be added to |
| | `deleted_at` | timestamptz | yes | soft delete only; a reason is required |
| | `created_at` | timestamptz | no | `DEFAULT now()` |
| `clinical_record_versions` | `id` | uuid | no | PK |
| | `tenant_id` | uuid | no | FK `tenants(id)` |
| | `clinical_record_id` | uuid | no | composite FK `(tenant_id, clinical_record_id)` |
| | `version` | integer | no | unique within the record; `CHECK (version >= 1)` |
| | `body` | text | no | the narrative, plaintext under RLS for search |
| | `body_format` | text | no | `CHECK IN ('MARKDOWN','PLAIN')` |
| | `author_id` | uuid | no | FK `users(id)` |
| | `signed_at` | timestamptz | yes | |
| | `supersedes_version` | integer | yes | corrections reference the version they replace |
| | `reason` | text | yes | API field `amendment_reason`; required when `version > 1` (R7) |
| | `created_at` | timestamptz | no | `DEFAULT now()` |
| | `signature_digest` | text | yes | **repo-proposed, no source field — OPEN-5** |

`UNIQUE (tenant_id, id)` on the parent lets the child use a tenant-bound composite FK (`04` §8). The
parent is never hard-deleted; a soft delete leaves its versions intact (`04` §6).

**The narrative is one column.** `04` §3.5 stores the narrative once in `body` and versions it; the
`subjective`/`objective`/`assessment`/`plan` authoring surface is serialisation over that single column,
not four columns and not a second table (R3). `12` §3 names `clinical_notes` but the doc 04 contract
governs; the `HEALTH_INFORMATION` vs `HIGHLY_SENSITIVE` conflict is OPEN-1 and 05 applies the stricter.

## Constraints, indexes and read order
- **Unique `(record_id, version)`** — `UNIQUE (tenant_id, clinical_record_id, version)`; R8, one row per version.
- **Version index** — `(tenant_id, clinical_record_id, version DESC)` (`04` §3.5).
- **Timeline index** — `(tenant_id, patient_id, signed_at DESC NULLS LAST)` on `clinical_records`; the 50 prior entries before a review.
- **Full-text index** — partial index over `body`; `now()` never in the predicate (`04` §3.5); narrative search is a care requirement (`02` §5.1).

Reads return versions `ORDER BY version ASC` (R9); the unique constraint makes the order total, so no
tie-breaker is needed and `current_version` is authoritative. Target: a record plus 50 prior versions
under **200 ms p95** (`20` §4; `21` §9), which these indexes make an index scan plus a bounded join.

## Immutability mechanism at two layers

1. **API — no route mutates a version.** `PATCH /api/v1/clinical-records/{id}` appends while unsigned;
   once `signed_at` is set it returns `403 NOTE_ALREADY_SIGNED` before any SQL runs. No `UPDATE` against
   `clinical_record_versions` exists in the repo, and a lint rule fails the build on one (R5, R6).
2. **Database, primary — the grant.** The app role holds exactly `SELECT, INSERT` on
   `clinical_record_versions`; `UPDATE`, `DELETE` and `TRUNCATE` are revoked, so a mutation raises
   `42501 insufficient_privilege`. `04-database-erd.md` §9: **"Enforcement is by grant, not by
   convention. A convention is bypassed by a determined developer; a missing privilege is not."**
3. **Database, defence in depth — the trigger.** A grant binds only its grantee, so
   `trg_clinical_record_versions_immutable`, a `BEFORE UPDATE OR DELETE` statement-level trigger,
   raises `CLINICAL_RECORD_VERSION_IMMUTABLE` for **every role, including the table owner and the
   migration role**. There is no role exemption and no disabling setting. It is repo-proposed (no
   source trigger exists) and must never be the only control nor dropped to make a migration pass.

## Database privileges (migration `00xx_clinical_records.sql`)

```sql
GRANT SELECT, INSERT ON clinical_records TO clinos_app;
GRANT UPDATE (current_version, signed_at, deleted_at) ON clinical_records TO clinos_app;
REVOKE DELETE, TRUNCATE ON clinical_records FROM clinos_app;
GRANT SELECT, INSERT ON clinical_record_versions TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON clinical_record_versions FROM clinos_app;
```

The column-scoped `UPDATE` applies the column-grant pattern of `04` §9, so `tenant_id`, `patient_id`,
`record_type` and `author_id` cannot be rewritten even by the app role. Audit events use feature 04's
append-only `audit_log` (`SELECT, INSERT` only).

## RLS

`ENABLE` and `FORCE ROW LEVEL SECURITY` on both tables; policy `AS RESTRICTIVE FOR ALL TO clinos_app`
with `USING`/`WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)`.
`FORCE` closes the owner bypass; the app role is not the owner and has no `BYPASSRLS`. `NULLIF` fails
closed: an unset or empty setting becomes `NULL`, and `tenant_id = NULL` matches no row. Context is set
with `SET LOCAL app.tenant_id` inside the transaction, never per pooled connection (`04` §8).

## Treating-relationship check

Read and write require permission **and** an active care relationship. `hasActiveCareRelationship(actor,
patient_id)` in the central policy layer (`06` §10) reads `care_relationships(tenant_id, practitioner_id,
patient_id, clinic_id, active_from, active_to, source)` under the same RLS policy; it is never inferred
from clinic membership and never widened to the tenant. Denial is `403 AUTHZ_CARE_RELATIONSHIP_DENIED`;
a tenant mismatch is decided first and returns `404`. `care_relationships` has no ERD table (OPEN-3).

## Endpoints

| Method and path | Permission | Treating relationship | Notes |
| --- | --- | --- | --- |
| `POST /api/v1/clinical-records` | `clinical_record:write` | required | creates the record and `version = 1`, unsigned |
| `GET /api/v1/clinical-records/{id}` | `clinical_record:read` | required | record plus versions, ascending |
| `GET /api/v1/clinical-records/{id}/versions/{version}` | `clinical_record:read` | required | one version; `404` if absent |
| `GET /api/v1/patients/{patient_id}/clinical-records` | `clinical_record:read` | required | timeline, cursor-paginated |
| `PATCH /api/v1/clinical-records/{id}` | `clinical_record:write` | required | appends while unsigned; `403 NOTE_ALREADY_SIGNED` once signed |
| `POST /api/v1/clinical-records/{id}/amendments` | `clinical_record:write` | required | append with `supersedes_version` + reason; same code path as `PATCH` |
| `POST /api/v1/clinical-records/{id}/sign` | `clinical_record:write` + author of the version | required | identity-bound; sets `signed_at` |

No `DELETE` endpoint exists (R12). The sign route is repo-added to satisfy `22` US-12 and adds no new
permission.

## Deny-by-default request path
1. Authenticate the session; deny `401` if missing or expired.
2. Resolve `tenant_id` from the session; a resource in another tenant is `404`, never `403`.
3. Check the permission for the role; deny `403` if not held.
4. Resolve the resource; `404` if it does not exist in this tenant.
5. Check the active treating relationship for `clinical_record:read`/`:write`; deny `403`.
6. Audit the decision, including refusals, before responding.
7. Validate the body against a strict Pydantic model; unknown fields are rejected `422`.
8. Open the transaction, `SET LOCAL app.tenant_id`, execute under RLS, and write the audit event in the
   same transaction.
9. Commit; return the standard envelope.

## Failure behaviour
| Failure | Behaviour |
| --- | --- |
| `PATCH` after signature | `403 NOTE_ALREADY_SIGNED`; no SQL executed; no row change |
| Concurrent amendment of the same version | unique violation; retry once with the next version, then `409 VERSION_CONFLICT`; never a lost update (R8) |
| Direct `UPDATE`/`DELETE` as the app role | `42501 insufficient_privilege` (primary layer) |
| Direct `UPDATE`/`DELETE` as owner or migration role | `CLINICAL_RECORD_VERSION_IMMUTABLE` (defence in depth) |
| Missing tenant setting | zero rows; the request is refused, never widened |
| Audit write fails | the clinical write does not complete; alert raised (fail closed) |
| Any other error | generic envelope with `request_id`; no narrative, no stack trace |

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| `care_relationships` named by `06` §10 but not defined in `04` | CSO + Engineering Lead | OPEN — blocked |
| Immutability trigger is repo-proposed defence in depth; confirm at Gate 2 | Security Lead + CTO | OPEN |
| Column-scoped `UPDATE` on `clinical_records` vs plain `UPDATE` plus an identity trigger | CTO | OPEN |
| Timeline index on `signed_at` vs `created_at` | Engineering Lead | OPEN |
