---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, definition of done
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: definition of done

The six-part test is from `24-definition-of-done.md`. Tick only with a link to evidence; an
unjustified blank is a failed check. **No part is Done with an open High or Critical finding.**

| # | Part | Done | Evidence |
|---|---|---|---|
| 1 | Functional: every acceptance criterion in `01-requirements.md` (R1–R15) has a passing test | [ ] | F1–F12 output |
| 2 | Security: tenant resolved from session and resource; RLS forced with `USING` + `WITH CHECK`; non-owner app role with no `BYPASSRLS`; strict schemas; step-up on config change | [ ] | S1–S12 output; policy and grant listings |
| 3 | Isolation tests pass in CI and assert **absence** across list, filter, sort, search, direct id, nested resource, export and cache | [ ] | S1, S5, S7, S8 output |
| 4 | Audit: `tenant.viewed`, `tenant.config_changed`, `clinic.created`, `clinic.updated`, `TENANT_CROSS_ACCESS_ATTEMPT` emitted with the full envelope; denials audited with equal fidelity | [ ] | A1–A5 output |
| 5 | Operations and compliance: classification applied, no HIGHLY_SENSITIVE or SECRET in logs or analytics, residency register updated, alerts on cross-tenant denials present | [ ] | Log/telemetry review; residency register entry |
| 6 | Deployment: image builds, scans clean, migration is expand-and-contract, verified in Staging against a real PostgreSQL with RLS enabled | [ ] | Migration run log; Staging verification |

## Gate sign-off and verification governance

**No self-approval: the person who delivers the work never signs its gate.** The verifier and the
approver are different named roles.

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
|---|---|---|---|---|
| CI / Automated | Schema lint fails on a tenant table with no policy (S7); grant inspection (`tenants` column grants, no `DELETE` on `clinics`); app role ownership and `BYPASSRLS` | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 2 — Database** | RLS `ENABLE` + `FORCE`; exact `NULLIF(current_setting('app.tenant_id', true), '')::uuid` in `USING` and `WITH CHECK`; no-context reads zero rows; forged `tenant_id` refused by `WITH CHECK`; pool-reuse test; app role non-owner and no `BYPASSRLS` | **Security Lead** | **CTO** | **❌ Gate 2 permits NO conditional pass. A partial pass is a failed gate.** (`26-security-gates.md` §3; `reference/gates.md`) |
| Gate 4 — APIs | Tenant resolved, never supplied; cross-tenant `404` not `403`; permission matrix; strict input validation; rate limits | **Security Lead** | **CTO** | Conditional pass available only for a non-clinical endpoint; **not** for tenant isolation |
| Independent compliance | Audit-trail integrity, residency register, contractual isolation expectations | **Privacy Officer / Compliance Lead** | **External auditor** | Periodic / pre-launch |

Gate 2's evidence set is: isolation test report, pool-reuse output, grant listing, policy definition,
schema-lint output (`26-security-gates.md` §3). A failed gate re-plans; it is not carried forward.

## Control matrix rows fed by this module

| Requirement | Source | Control | Evidence | Owner | Status |
|---|---|---|---|---|---|
| Tenant isolation is enforced below the application | *Privacy Act 1988 (Cth)* APP 11 | RLS with `FORCE`; restrictive policy; fail-closed setting | S1, S5, S7 | Security Lead | planned |
| No tenant context leaks through pooling | Internal; PgBouncer transaction-mode behaviour | `SET LOCAL` inside the transaction only; reset proven; plain `SET` forbidden | S1 | Head of Platform | planned |
| Least privilege at the database | ACSC Essential Eight | Dedicated non-owner role, explicit grants, no `BYPASSRLS` | S6, S9, S10 | Security Lead | planned |
| A tenant table with no policy fails CI | Internal | Schema lint over `pg_class` and `pg_policies` | S7 | Security Lead | planned |
| A request with no tenant context reads nothing | *Privacy Act 1988 (Cth)* APP 11 | Fail-closed `NULLIF` policy; helper refuses to open a transaction | S2 | Security Lead | planned |
| A forged `tenant_id` in a write is refused | Internal | `WITH CHECK` on every policy; caller value ignored and audited | S3, A4 | Security Lead | planned |
| Tenant identity is resolved, never supplied | Internal (`00-README.md` rule 3) | Tenant from session and resource; client value dropped and audited | F2, A4 | Security Lead | planned |
| Isolation holds across every leakage channel | OWASP API1:2023 | Context carried into API, workers, cron, queue, export, cache, storage, search, webhooks, analytics | S8 | Security Lead | planned |
| Cross-tenant authorisation denials are alerted | *Privacy Act 1988 (Cth)*; Notifiable Data Breaches scheme | Alert on `TENANT_CROSS_ACCESS_ATTEMPT` with a documented assessment path | A4 | Security Lead | planned |
| Contractual isolation expectations | Customer contracts, unseen | Nothing claimed beyond shared schema plus RLS | Contract review record | Commercial Lead | REQUIRES LEGAL/REGULATORY VALIDATION |

## Open items blocking Done

| Item | Owner | Status |
|---|---|---|
| OPEN-1 `clinics` column set, constraints and classification unspecified by the ERD | Head of Platform + Privacy Officer | OPEN |
| OPEN-2 `tenant:read`, `clinic:read`, `clinic:manage` absent from the fixed permission catalogue; tenancy routes cannot pass Gate 4 | CTO | OPEN |
| OPEN-3 Route shape `/api/v1/clinics` vs `/admin/clinics` before Gate 4 | Head of Platform | OPEN |
| OPEN-4 Missing-context status (`403` vs `500` vs `401`) | Security Lead | OPEN |
| OPEN-5 Tenant soft-delete against the four-value status vocabulary | CTO + Privacy Officer | OPEN |
| OPEN-6 Contractual schema/database separation or per-tenant keys | Commercial Lead + Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-7 Pooler configuration per environment, including `server_reset_query`, before S1 is accepted as evidence | Head of Platform | OPEN |
