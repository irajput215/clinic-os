---
doc_id: FEAT-TEN-01
title: Tenancy and clinics, threat model
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 05-tenant-isolation, 04-database-erd, 06-authentication-rbac
---

# Tenancy and clinics: threat model

## Risk-scoring method
Likelihood × Impact, each 1–5 (`03-threat-model.md` §2). Band: **Low ≤4**, **Medium 5–9**,
**High 10–16**, **Critical ≥17**. The band is computed from the product using the published band table.
A residual of 5 or more is never accepted silently; every row names a human role as owner.

## STRIDE assessment and residual risk register

| ID | STRIDE | Threat and attack path | Inherent | Control / mitigation | Residual | Owner | Source |
|---|---|---|---|---|---|---|---|
| **T-TEN-1** | Spoofing | **Tenant ID supplied by the client.** Attacker puts another tenant's `tenant_id` in the body, header, query string or subdomain, hoping the request honours it. | High (3×5=15) | Resolve tenant from the verified session claim **and** the addressed resource; a supplied value is ignored and audited `TENANT_CROSS_ACCESS_ATTEMPT`; RLS is the backstop. | **Low (1×4=4)** | Security Lead | `05 §"How to take this point"; 20 §1; 06 §10` |
| **T-TEN-2** | Tampering | **Connection-pool cross-tenant bleed.** A session-level `SET app.tenant_id` survives commit on a transaction-pooled server connection; the next request inherits the previous tenant and every policy evaluates wrongly. | High (3×5=15) | `SET LOCAL` inside the transaction only; plain `SET` prohibited by lint and review; `server_reset_query = DISCARD ALL`; no transaction held across a network call; concurrent pooled test. | **High (2×5=10)** | Head of Platform | `05 §3; 21 §2; 03 §10` |
| **T-TEN-3** | Information disclosure | **A missing filter relying on RLS.** A new repository method or hand-written query omits the tenant predicate, or a join applies it to the parent only. | Critical (4×5=20) | One `AS RESTRICTIVE` policy with the `NULLIF` guard and `WITH CHECK` on every tenant table; `FORCE ROW LEVEL SECURITY`; repository predicate; schema lint; `rls.holds_without_app_filter`. | **Medium (2×4=8)** | Engineering Lead | `05 §1, §8 I-016, I-019; 03 §10` |
| **T-TEN-4** | Information disclosure | **A query path with no tenant context.** A background job, export or new route opens a transaction and reads unscoped, or a default tenant is configured. | High (3×5=15) | The transaction helper refuses to open without context; the policy matches nothing (`tenant_id = NULL`); no default-to-all path; `rls.no_context_returns_zero_rows`. | **Medium (1×5=5)** | Engineering Lead | `05 §2, §6, I-017; 21 §2` |
| **T-TEN-5** | Elevation of privilege | **Suspended-tenant access.** A `SUSPENDED` or `CLOSING` tenant keeps reading health information with a valid unexpired session because status is only checked at login. | High (3×4=12) | Tenant status enforced at resolution on **every** request, before a transaction opens; refusal audited. | **Low (1×4=4)** | Security Lead | `20 §1; 05 §9 fixture D` |
| **T-TEN-6** | Information disclosure | **Cross-tenant enumeration.** Attacker varies list, filter, sort, search, direct id, nested resource, export or cache parameters to surface another tenant's clinics. | High (3×4=12) | Absence assertions across all eight channels; `404` never `403`; opaque UUIDv4 identifiers; result caps; tenant-namespaced cache keys; slug is never an authorisation input. | **Low (1×4=4)** | Security Lead | `05 §8 I-001–I-035; 21 §2; 20 §1` |
| **T-TEN-7** | Tampering | **An unset tenant matches everything.** A policy written without the `NULLIF` guard coerces the absent setting to `''` and raises or, worse, a default tenant is supplied so an empty context silently matches. | High (3×5=15) | `NULLIF(current_setting('app.tenant_id', true), '')::uuid` required in `USING` **and** `WITH CHECK`; lint asserts the exact expression; a negative control proves the naive form raises. | **Low (1×4=4)** | Security Lead | `05 §2; 04 §8` |
| **T-TEN-8** | Elevation of privilege | **Owner / `BYPASSRLS` bypass.** The application connects as the table owner or a role holding `BYPASSRLS`, silently disabling every tenant policy. | High (2×5=10) | Dedicated non-owner app role with no `BYPASSRLS`; `FORCE ROW LEVEL SECURITY`; `rls.app_role_is_not_owner` after every migration. | **Medium (1×5=5)** | Security Lead | `05 §4, §5.2, I-020; 26 Gate 2` |
| **T-TEN-9** | Repudiation | **A cross-tenant attempt is refused but not recorded.** The denial is dropped, so probing is invisible and the control cannot be evidenced. | High (3×4=12) | Denied and failed attempts audited with the same fidelity as successes; `TENANT_CROSS_ACCESS_ATTEMPT` with the full envelope, written in the same transaction; a failed audit write fails the action closed. | **Low (1×4=4)** | Security Lead | `07 §1–§2; 02 §1 control 6; README non-negotiable rules` |
| **T-TEN-10** | Denial of service | **Tenancy-route flood.** A tenant floods `/api/v1/tenants/*` or `/api/v1/clinics/*` to exhaust the shared pool or worker capacity. | Medium (3×3=9) | Edge WAF rules plus application limits keyed on session and tenant (administrative class 20/min, reads 300/min); `429` with `Retry-After`; per-tenant quotas. | **Low (2×2=4)** | Head of Platform | `02 §11` |

All seven required attack paths are covered: client-supplied tenant id (T-TEN-1), pool bleed (T-TEN-2),
missing filter (T-TEN-3), no tenant context (T-TEN-4), suspended tenant (T-TEN-5), cross-tenant
enumeration (T-TEN-6), and unset tenant matching everything (T-TEN-7).

## Assumptions
- Single database, modular monolith, shared schema, RLS enabled and forced.
- Identity and session verification are provided by feature 02; this feature consumes a resolved tenant.
- The source register's numeric scores are reused where given; the **band is recomputed** from the
  product. Source prose sometimes disagrees (source `03` §10 labels the pool leak "Medium (2×5)",
  while 2×5=10 is High under the published band table). The computed band governs.

## Open items
| Item | Owner | Status |
|---|---|---|
| Residual band of T-TEN-2 (pool bleed): source prose says Medium, the band table makes 2×5 High | Security Lead | OPEN |
| Pooler configuration per environment before T-TEN-2 is treated as controlled | Head of Platform | OPEN |
| Alert severity and notification timing when a cross-tenant denial fires | Security Lead + legal adviser | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether a customer contract requires schema/database separation or per-tenant keys, which would change the isolation model | Commercial Lead + Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Insider read inside one tenant (source TH-015) is out of scope here; owned by the audit and access-review features | Practice Owner | OPEN |
