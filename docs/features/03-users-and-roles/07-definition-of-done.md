---
doc_id: FEAT-USR-07
title: Users and roles, definition of done
owner: CTO
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 04-database-erd, 20-product-requirements
---

# Definition of Done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence. No part is Done
with an open High or Critical finding.

| # | Part | Done | Evidence |
| --- | --- | --- | --- |
| 1 | **Functional:** every acceptance criterion in [01-requirements.md](01-requirements.md) R1–R14 has a passing test in [06-test-plan.md](06-test-plan.md) | [ ] | `tests/rbac`, `tests/users` CI run; R→F/S mapping in the traceability line |
| 2 | **Security:** deny-by-default path, central policy layer, RLS, grantability rule, step-up, strict schemas implemented | [ ] | `tests/security/test_users_rbac.py`, `tests/isolation/test_users_isolation.py`, `tests/security/test_authz_recomputes_server_side.py` |
| 3 | **Security tests pass in CI:** S1–S15, including the role × endpoint matrix | [ ] | CI security test report; `tests/security/test_users_rbac.py::test_role_endpoint_matrix_403_without_permission` |
| 4 | **Audit:** the seven events emitted with the full envelope and verified; A1–A5 | [ ] | `tests/users/test_audit.py`; a sample event carrying the envelope from `05-data-and-audit.md` |
| 5 | **Operations & compliance:** classification applied, no secret or credential in a log, residency register updated, admin rate limit and alerts present | [ ] | `tests/security/test_no_phi_in_log_payload.py`; vendor/residency register entry; rate-limit test S15 |
| 6 | **Deployment:** image builds, scans clean, migration expand-and-contract, verified in Staging | [ ] | CI pipeline record; migration review; Staging verification note |

## Gate sign-off & Verification Governance

**No self-approval.** The person who delivered the work never signs its gate. Source:
[`../../reference/gates.md`](../../reference/gates.md); `26-security-gates.md` §4.

| Stage / Gate | What is verified | Verifier (decision maker) | Approver | Pass policy |
| --- | --- | --- | --- | --- |
| **CI / Automated** | Role × endpoint matrix, grant inspection (`information_schema.role_table_grants`), `test_authz_recomputes_server_side` | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 3 (Authentication)** | RBAC tests show a user without a permission receiving `403` on every protected route; the central policy layer is in place; roles and permissions seed data exists | Security Lead | CTO | MFA and step-up have **no** conditional pass |
| **Gate 4 (APIs)** | Vertical and horizontal escalation fail; the actor cannot grant what they lack; self-grant refused; cross-tenant `404`; strict schemas; rate limits | Security Lead | CTO | No conditional pass for a failing authorisation test (Critical until fixed) |
| **Independent compliance** | Append-only access-change evidence, access-review baseline, offboarding timestamps | Privacy Officer / Compliance Lead | External auditor | Periodic / pre-launch |

> **Gate 3 is BLOCKED by D-003.** The `users` credential columns, the session/revocation design and the
> step-up mechanism are unresolved. Gate 3 cannot be signed until the identity decision closes. See
> [`../../reference/decisions/D-003-identity-model.md`](../../reference/decisions/D-003-identity-model.md).

## Control matrix rows fed by this module

| Requirement | Control | Implementation | Evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Roles are thin bundles over granular permissions | Central policy layer; roles resolve to permission sets | `can(actor, permission, resource)` | S1, S2, F1 | Security Lead | planned |
| Every authorisation decision is recomputed server-side | No server-side authz cache without a tenant and resource key | `backend/app/modules/rbac/policy.py` | S1 | CTO | planned |
| An actor cannot grant a permission the actor does not hold | Server-side grantability rule; step-up | grant path + `GRANT_EXCEEDS_ACTOR` | S5, S6, S7 | Security Lead | planned |
| Offboarding revokes access immediately | Server-side session revocation; non-`ACTIVE` actor refused | deactivate endpoint + policy check | S8, F7 | Security Lead | planned |
| A clinic cannot see another clinic's users or roles | RLS with `FORCE`; tenant from the session; `404` across a boundary | `users`/`roles`/grant RLS policies | S3, S4, S10, S11 | CTO | planned |
| Privileged access is demonstrably current | Periodic access review with last-review dates | review job + `ACCESS_REVIEW_COMPLETED` | F8, A5 | Compliance Lead | planned |
| Access changes are append-only evidence | `GRANT SELECT, INSERT` on `audit_log`; `UPDATE`/`DELETE`/`TRUNCATE` revoked | `information_schema.role_table_grants` + negative SQL | A1–A4, S12 | Security Lead | planned |
| Identity data stays in Australia | Residency register; region-pinned storage | register entry | register entry | Compliance Lead | planned |

## Open items blocking Done

| Item | Owner | Status |
| --- | --- | --- |
| **D-003** identity model — blocks Gate 3 and the `users` credential columns | CTO + Security Lead | OPEN — requires a decision |
| **OPEN-1** permission catalogue reconciliation (19 vs 20 vs the doc 20/22 candidates) — blocks the seed migration and the matrix test | CTO + Security Lead | OPEN |
| **OPEN-2** whether a tenant may create custom roles | CTO | OPEN |
| Whether the Pharmacy and access-review stories are in MVP scope | Head of Product + Compliance Lead | OPEN |
| Whether `permission:grant`/`permission:revoke` are distinct codes or part of `users:manage` | Security Lead | OPEN |
| The event-name authority (uppercase names vs doc 07 §1 lowercase dot form) | CTO + Compliance Lead | OPEN |
| Retention period for user, role and permission-change audit events | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Identity-provider residency and sub-processor position (if D-003 Option A) | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
