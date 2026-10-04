---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, design
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: design

Shared-schema multi-tenancy. Every tenant table carries `tenant_id NOT NULL`; PostgreSQL RLS is the
backstop below the application filter. (`05-tenant-isolation.md` §1–§2; `21-technical-design.md` §2.)

## Table: `tenants` (GLOBAL — no RLS)

| Column | Type | Null | Notes | Class |
|---|---|---|---|---|
| `id` | uuid | no | PK, `gen_random_uuid()` | INTERNAL |
| `slug` | text | no | unique, lower-case; routing only, **never an authorisation input** | INTERNAL |
| `legal_name` | text | no | the practice entity | CONFIDENTIAL |
| `status` | text | no | `CHECK IN ('ACTIVE','SUSPENDED','CLOSING','CLOSED')` | INTERNAL |
| `data_region` | text | no | `ap-southeast-2` only in this release | INTERNAL |
| `retention_profile` | text | no | references a named retention schedule | CONFIDENTIAL |
| `created_at`, `updated_at` | timestamptz | no | | INTERNAL |

PK `(id)`. Unique `(slug)`. **No RLS: `tenants` is global** — context is proven from the actor's
identity, not read from this table (`04 §3.1`); protection is column-level grants plus status enforcement.

## Table: `clinics` (tenant-scoped)

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | uuid | no | PK |
| `tenant_id` | uuid | no | FK `tenants(id)` ON DELETE RESTRICT; RLS key; index leads with it |
| `created_at`, `updated_at` | timestamptz | no | ERD convention §3 |

`clinics` belongs to tenancy administration (`20 §1`; `21 §8`) and is tenant-scoped with
`tenant_id NOT NULL` (`20 §1`); it has a human-readable label because US-02 requires create and rename.
Its column set, uniqueness rules and classification are **OPEN** (Head of Platform + Privacy Officer) and
are **not invented here**; `UNIQUE (tenant_id, id)` is expected for tenant-bound child keys (`04 §8`).

## RLS policy

```sql
ALTER TABLE clinics ENABLE ROW LEVEL SECURITY;
ALTER TABLE clinics FORCE ROW LEVEL SECURITY;   -- closes the owner bypass

CREATE POLICY pol_clinics_tenant_isolation ON clinics
  AS RESTRICTIVE
  FOR ALL
  TO clinos_app, clinos_readonly_audit, clinos_retention
  USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

- **Fail closed.** An unset or empty `app.tenant_id` becomes `NULL`; `tenant_id = NULL` is never true,
  so a lost context returns **zero rows** instead of every row.
- **Both directions.** `USING` restricts what is visible; `WITH CHECK` restricts what may be written.
- **Restrictive combination.** `AS RESTRICTIVE` combines with `AND`, so a later permissive policy cannot
  widen access past the tenant boundary.
- **Owner bypass closed.** `FORCE` applies to the owner too, and the app role is a non-owner (`05 §2`; `04 §8`).

## Database privileges

The application connects as `clinos_app`: non-owner, no `BYPASSRLS`; roles are created by migration, never by hand (`05 §4`).

```sql
-- tenants is global: column-level grants only, read-only to the application
REVOKE ALL ON tenants FROM clinos_app;
GRANT SELECT (id, slug, status, data_region) ON tenants TO clinos_app;  -- retention_profile withheld

-- clinics is tenant-scoped: no DELETE where retention may apply
GRANT SELECT, INSERT, UPDATE ON clinics TO clinos_app;
REVOKE DELETE, TRUNCATE ON clinics FROM clinos_app;
ALTER TABLE clinics OWNER TO clinos_migrator;   -- clinos_app never owns a table
```

## The connection-pool hazard

Tenant context is set **inside the transaction that runs the query, and nowhere else** (`05 §3`).

```sql
BEGIN;
SET LOCAL app.tenant_id  = '<uuid>';   -- transaction-scoped; reverts at COMMIT or ROLLBACK
SET LOCAL app.actor_id   = '<uuid>';
SET LOCAL app.request_id = 'req_...';
COMMIT;                                 -- the queries run between BEGIN and COMMIT
```

| Configuration | Consequence |
|---|---|
| No pooler / session pooling | Safe, but the connection count is not reduced; hides the bug |
| **PgBouncer, transaction pooling** | **A session-level `SET` leaks across tenants — the trap** |
| RDS Proxy | Pins a session on session-state change; reduces but does not eliminate risk |

A plain `SET app.tenant_id` survives commit on the server connection; the next request on that
connection — possibly another tenant — has **every RLS policy evaluate against the wrong tenant**. Rules:
`SET LOCAL` only, `DISCARD ALL` on check-in as belt-and-braces, no transaction across a network call, and
a concurrent pooled test (`05 §3`; test S1).

## Tenancy channels tenant context must reach (`05 §6`)

| Channel | How tenant is established | Failure behaviour |
|---|---|---|
| API middleware | verified token claim → request context; the DB helper refuses to open without it | throws before the transaction opens; never an unscoped query |
| Workers, queue consumers, cron jobs | `tenant_id` in the envelope (schema-validated); cron iterates one tenant per transaction | missing/malformed → DLQ + alert; no default tenant; never one query across all tenants |
| Report exports | tenant from the caller's context, re-checked at download | stale authorisation → refused, not served |
| Cache keys | mandatory builder, prefixed `t:{tenant_id}:` and `p:{patient_id}:` | a key built without a tenant throws in dev and test |
| S3 prefixes and presigned URLs | `tenants/{tenant_id}/...`; IAM conditions on the prefix; 5-minute TTL; client cannot supply the key | presigner refuses a key outside the caller's prefix; URL cannot be edited to reach another object |
| Search indexes | one index or alias per tenant, `clinics_{tenant_id}` | a missing alias is a configuration error, not a fallback |
| Webhooks | per-tenant endpoint and signing secret, matched before processing | unmatched signature/tenant → `401`, logged, alerted |
| Analytics and telemetry | no tenant- or patient-identifying properties | a property outside the allow-list fails the schema test |

## Endpoints

| Method and path | Permission | Notes |
|---|---|---|
| `GET /api/v1/tenants/current` | `tenant:read` (OPEN-2) | resolved tenant only; no tenant in the path |
| `PATCH /api/v1/tenants/current` | `tenant:configure` | step-up 5 min; security setting change versioned |
| `GET /api/v1/tenants/current/clinics` | `clinic:read` (OPEN-2) | cursor-paginated; bounded `limit` |
| `POST /api/v1/clinics` | `clinic:manage` (OPEN-2) | tenant from session; body `tenant_id` rejected |
| `PATCH /api/v1/clinics/{id}` | `clinic:manage` (OPEN-2) | `404` on cross-tenant; collision `422`, not `500` |

The prefix is D-005; the PRD's `/admin/clinics` shape is OPEN-3. No `DELETE` endpoint (deletion is OPEN).

## Deny-by-default request path
1. Authenticate the session — deny `401` if missing or expired.
2. Resolve tenant from the verified token claim **and** the addressed resource; enforce `status = ACTIVE`
   at resolution — deny if unresolvable or suspended.
3. Open the transaction; the helper refuses to open without tenant context.
4. `SET LOCAL app.tenant_id`, `app.actor_id`, `app.request_id` inside that transaction.
5. Authorise in the central policy layer: resource tenant ≠ actor tenant → `404`; permission not held → `403`.
6. Validate the body against a strict schema — unknown fields rejected, so a body `tenant_id` is `422`.
7. Execute inside the RLS-scoped transaction.
8. Audit the decision, including the refusal, in the same transaction; a failed audit write fails the action.

## Failure behaviour
Fails **closed** on any tenant-resolution, authorisation or database error; errors use the standard
envelope with a `request_id` and leak no stack trace or tenant data. Cross-tenant access is `404`; no
context yields zero rows plus a refusal; a rename collision is `422`; a suspended tenant is refused.

## Open items
| Item | Owner | Status |
|---|---|---|
| `clinics` column set, constraints and classification | Head of Platform + Privacy Officer | OPEN |
| Pooler configuration per environment, including `server_reset_query`, before test S1 is evidence | Head of Platform | OPEN |
| Clinic delete/retention position | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
