---
doc_id: FEAT-USR-04
title: Users and roles, threat model
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Users and roles, threat model

## Risk assessment methodology (5×5 matrix)
Risk score is `Likelihood (1–5) × Impact (1–5)`.

- **Low ≤4** — acceptable residual; standard telemetry.
- **Medium 5–9** — managed; requires automated CI test verification.
- **High 10–16** — must be mitigated before pilot deployment.
- **Critical ≥17** — catastrophic; **blocks release outright**.

Authentication mechanics (credential theft, MFA bypass, session fixation, step-up replay) are threats of
feature 02 and are **not duplicated here**; this model covers the authorisation, role and user-lifecycle
surface. Sources: `06-authentication-rbac.md` §9–§12; `04-database-erd.md` §3.2–§3.3, §8–§9;
`20-product-requirements.md` §1–§2; `22-user-stories.md` US-05, US-06, US-07, US-14, US-29, US-30.

## STRIDE assessment and residual risk matrix

| ID | STRIDE | Threat and attack path | Inherent Risk | Control / Mitigation | Residual Risk (L×I, band) | Owner | Source |
| --- | --- | --- | :---: | --- | :---: | --- | --- |
| **T-03.1** | **Elevation** | **Horizontal privilege escalation.** A Doctor changes the object identifier to reach a peer's patient or record: object-level authorisation is assumed from the route, not evaluated per object | High (4×4=16) | `can(actor, permission, resource)` evaluates a resource rule on every request; care-relationship lookup runs under the same RLS policy; cross-tenant returns `404` | **Low (1×4=4)** | Security Lead | `06 §10; 26 §5` |
| **T-03.2** | **Elevation** | **Vertical escalation by role assignment.** An Administrator assigns themselves or another user a role whose bundle contains `tenant:configure`, `prescription:sign` or `audit:read` | Critical (4×5=20) | The grantability rule refuses any bundle containing a permission the actor does not hold; `users:manage` never includes `tenant:configure`; step-up required; assignment audited | **Low (1×4=4)** | CTO | `06 §9, §12; 20 §2` |
| **T-03.3** | **Elevation** | **Self-granting a permission.** An actor holding `users:manage` adds a missing permission to their own role or account to widen their own access | High (3×5=15) | Server-side grantability check; self-grant is not exempt; step-up bound to the operation and resource; previous and new sets recorded | **Low (1×4=4)** | Security Lead | `06 §8–§9; 22 US-06` |
| **T-03.4** | **Elevation** | **Confused deputy.** An actor uses a privileged endpoint to grant a permission they do not hold, on the assumption the endpoint itself is authorised | High (4×4=16) | The permission set is re-derived from the actor's roles, never from the request; the endpoint's own permission is not sufficient to grant a permission the actor lacks | **Low (1×4=4)** | Security Lead | `06 §9–§10` |
| **T-03.5** | **Elevation** | **Stale role cache.** A revoked role or permission continues to authorise because a decision or capability list was cached from a previous request | High (3×4=12) | Decision recomputed per request from the verified identity, tenant and resource; no server-side authorisation cache without a tenant and resource key; refresh refused on change; access tokens ≤10 min | **Low (2×2=4)** | CTO | `06 §3, §10–§11; 02 §1 control 2` |
| **T-03.6** | **Spoofing** | **Deactivated account retains access.** An offboarded user keeps using a live access token or refresh family until natural expiry | High (3×4=12) | Deactivation revokes every session and refresh family within 60 seconds; the policy layer refuses a non-`ACTIVE` actor; outstanding access tokens expire within 10 minutes | **Low (1×4=4)** | Security Lead | `06 §3; 22 US-07` |
| **T-03.7** | **Elevation** | **Orphaned role grant.** A role or user is removed while a grant row survives, or a grant references a deleted role, leaving an unintended permission | High (3×4=12) | FK `ON DELETE RESTRICT` on grants; system roles not deletable; deactivation revokes sessions; the access review flags accounts without a current review date | **Low (2×2=4)** | CTO | `04 §3.3; 22 US-30` |
| **T-03.8** | **Information disclosure** | **Staff enumeration across tenants.** An attacker probes user or role identifiers to confirm a person exists at another clinic | High (3×4=12) | RLS with `FORCE`; tenant from the session; cross-tenant returns `404` not `403`; uniform error bodies; object identifiers are random UUIDv4 | **Low (1×4=4)** | Security Lead | `04 §8; 06 §11–§12` |
| **T-03.9** | **Tampering** | **Tenant-invented permission.** A tenant inserts a new permission code or mutates a system role's code to widen a bundle | Medium (3×3=9) | `permissions` is global reference data granted `SELECT` only; system role codes are constrained and not deletable; tenant edits are limited to a display name | **Low (1×3=3)** | CTO | `04 §3.3` |
| **T-03.10** | **Repudiation** | **Access-change denial.** An administrator denies having granted or revoked a permission | High (3×4=12) | `USER_CREATED`, `USER_DEACTIVATED`, `ROLE_ASSIGNED`, `ROLE_REVOKED`, `PERMISSION_GRANTED`, `PERMISSION_REVOKED` written append-only in the same transaction, with `actor_role` at decision time | **Low (1×4=4)** | Compliance Lead | `07 §1–§2, §5; 22 US-30` |
| **T-03.11** | **Denial of service** | **Admin-endpoint flood.** Brute-force or scripted abuse of `/users/*` and `/roles/*` to exhaust the pool or enumerate | Medium (3×3=9) | Administrative endpoint class limited to 20 requests/minute per session; step-up required; WAF as the first layer | **Low (2×2=4)** | Head of Platform | `02 §11` |

## Assumptions
- Identity is verified by feature 02; this feature trusts only the verified actor and its tenant.
- Single database, modular monolith, RLS enabled; the app role is not the table owner and has no
  `BYPASSRLS`.
- The seven role codes and 19 catalogue permissions are the MVP set; candidate codes are not granted
  until OPEN-1 closes.

## Open items
| Item | Owner | Status |
| --- | --- | --- |
| Whether a practitioner across two clinics is two user rows or one identity, and its effect on T-03.7 | Engineering Lead + Clinical Safety Officer | OPEN |
| Whether insider-risk monitoring of staff access is required by a tenant contract, and its privacy basis | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Whether a tenant may create custom roles, which would add a tampering path covered by T-03.9 | CTO | OPEN |
| Residual-risk acceptance for any High finding before pilot deployment | Practice Owner + CTO | OPEN |
