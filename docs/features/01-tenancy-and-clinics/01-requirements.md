---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, requirements
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: requirements

## Purpose
Model each customer organisation (`tenants`) and its practice sites (`clinics`), and prove that one
tenant's data is unreachable from another. Isolation is enforced in PostgreSQL, not by convention.
(`clinic-os-secure-by-design/20-product-requirements.md` §1; `21-technical-design.md` §2.)

## The tenant identity principle
**Tenant identity is resolved from the authenticated session and the addressed resource. It is never
supplied by the client** — not by request body, header, query parameter or subdomain.
(`05-tenant-isolation.md` "How to take this point"; `06-authentication-rbac.md` §10.)
- A client-supplied `tenant_id` is **ignored**, and the mismatch is audited as a cross-tenant denial.
- A missing or unresolvable tenant is a **denial**, never "all tenants".
- Tenant **status is enforced at resolution on every request**, not only at login.

## Requirements

| ID | Requirement | Acceptance (testable) | Verified by |
|---|---|---|---|
| **R1** | Resolve tenant from session + addressed resource | `tenant_id` in body, header, query or subdomain is ignored; response contains only the caller's tenant data; a `TENANT_CROSS_ACCESS_ATTEMPT` event is written | `tests/tenancy/test_tenant_resolution.py::test_supplied_tenant_id_is_ignored_and_audited` |
| **R2** | `tenants` matches the ERD | Columns and `CHECK (status IN ('ACTIVE','SUSPENDED','CLOSING','CLOSED'))`; `UNIQUE (slug)`, lower-case; slug is routing only and **never an authorisation input** | `tests/tenancy/test_tenants.py::test_tenant_status_controlled_vocabulary` |
| **R3** | `clinics` is tenant-scoped | `tenant_id uuid NOT NULL` FK `tenants(id)` ON DELETE RESTRICT; `FORCE ROW LEVEL SECURITY`; full column set is **OPEN** (see below) | `tests/tenancy/test_clinics.py::test_clinic_table_is_tenant_scoped` |
| **R4** | RLS on every tenant table | `ENABLE` + `FORCE ROW LEVEL SECURITY`; one `AS RESTRICTIVE` policy with `USING` **and** `WITH CHECK` | `tests/isolation/test_role_and_policy_coverage.py::test_every_tenant_table_has_forced_policy` |
| **R5** | App role cannot bypass RLS | `clinos_app` is not the table owner and does not hold `BYPASSRLS` | `tests/isolation/test_role_and_policy_coverage.py::test_app_role_is_not_owner_and_has_no_bypassrls` |
| **R6** | No tenant context reads nothing | A raw query with `app.tenant_id` unset returns **zero rows and no error**, and the request is refused | `tests/isolation/test_no_tenant_context.py::test_no_tenant_context_reads_zero_rows_and_is_refused` |
| **R7** | Forged tenant on a write is refused | `INSERT`/`UPDATE` with another tenant's `tenant_id` raises `new row violates row-level security policy`; no row is moved | `tests/isolation/test_with_check_blocks_cross_tenant_insert.py::test_forged_tenant_id_write_rejected` |
| **R8** | `SET LOCAL` only, inside the transaction | No session-level `SET app.*`; concurrent pooled requests on one connection show zero bleed | `tests/isolation/test_pool_reuse.py::test_connection_pool_reuse_no_tenant_leak` |
| **R9** | Cross-tenant access is `404`, never `403` | Direct id, nested resource and export return `404` with no existence leak; denied attempts are audited with equal fidelity | `tests/isolation/test_clinics_absence.py::test_cross_tenant_never_returns_403` |
| **R10** | Tenant status enforced at resolution | A `SUSPENDED` tenant is refused on every request even with a valid unexpired session | `tests/tenancy/test_tenant_resolution.py::test_suspended_tenant_refused_on_every_request` |
| **R11** | Clinic create/rename is tenant-scoped | A clinic created under tenant A is invisible to tenant B in list, filter, sort, search, direct id, export and cache; a rename collision returns `422`, not `500` | `tests/isolation/test_clinics_absence.py::test_absence_across_list_filter_sort_search_id_nested_export_cache` |
| **R12** | Security-config change requires step-up | `PATCH` without a fresh factor is refused `403`; after step-up the change is versioned with actor and timestamp | `tests/security/test_tenancy_step_up.py::test_tenant_security_config_requires_step_up` |
| **R13** | Schema lint fails CI on drift | Any table with a `tenant_id` column and no forced policy fails the build; any table without `tenant_id` is on the global allow-list (`tenants`, `permissions`, `schema_migrations`) | `tests/isolation/test_role_and_policy_coverage.py::test_schema_lint_fails_when_tenant_table_lacks_policy` |
| **R14** | Absence assertions across every channel | Isolation is proven absent across list, filter, sort, search, direct id, nested resource, export and cache — not merely that the expected row appears | `tests/isolation/test_clinics_absence.py::test_clinics_absent_in_every_channel` |
| **R15** | Abuse protection on tenancy routes | `/api/v1/tenants/*` maps to the administrative class (20/min); single-resource reads to 300/min; breach returns `429` with `Retry-After` | `tests/security/test_tenancy_rate_limits.py::test_admin_class_rate_limit_returns_429` |

Sources: `05-tenant-isolation.md` §2–§8; `04-database-erd.md` §3.1, §8; `06-authentication-rbac.md` §10, §12;
`20-product-requirements.md` §1; `02-security-architecture.md` §1 control 3, §11; `26-security-gates.md` Gate 2.

## Out of scope
- Identity, sessions, MFA, step-up mechanics — feature 02 (blocked by D-003).
- Users, roles, permission grants — feature 03.
- `audit_log` storage, envelope implementation and export — feature 04.
- Feature flags, retention-job execution, break-glass — feature 15.
- Deployment target and residency implementation — D-004 and `13-data-residency.md`.

## Open items
| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | `clinics` columns and per-field classification are not specified by the ERD; only `id`, `tenant_id` and the standard timestamps are known | Head of Platform + Privacy Officer | OPEN |
| OPEN-2 | `tenant:read`, `clinic:read`, `clinic:manage` (PRD §1) are absent from the fixed 19-permission catalogue (`04 §3.3`; `06 §9`); tenancy routes cannot pass Gate 4 until reconciled | CTO | OPEN |
| OPEN-3 | Route shape: PRD §1 uses `/tenants/current/clinics` and `/admin/clinics`; D-005 mandates the `/api/v1` prefix | Head of Platform | OPEN |
| OPEN-4 | Missing-context status: `20 §1` says `403`; `05 §6` says the handler returns `500`; `06 §10` says `401 NO_IDENTITY` | Security Lead | OPEN |
| OPEN-5 | Tenant deletion: `20 §1` describes a soft-deleted tenant, but the ERD status vocabulary has no `DELETED` value | CTO + Privacy Officer | OPEN |
| OPEN-6 | Whether a contract requires schema/database separation or per-tenant encryption keys | Commercial Lead + Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-7 | Audit-name form: `07 §1` uses lowercase dot; `20 §1` uses `UPPER_SNAKE` (`CLINIC_CREATED`) | CTO | OPEN |
