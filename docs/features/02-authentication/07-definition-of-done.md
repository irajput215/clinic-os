---
doc_id: FEAT-AUTH-07
title: Authentication, definition of done
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: definition of done

The six parts are from `24-definition-of-done.md`. Tick only with a link to evidence. **No part is Done
with an open High or Critical finding.**

| # | Part | Done | Evidence link |
|---|---|:---:|---|
| 1 | Functional: every acceptance criterion in 01-requirements.md (R1–R14) has a passing test | [ ] | F1–F15 test report; `docs/features/02-authentication/06-test-plan.md` |
| 2 | Security: deny-by-default path, MFA enforcement, token verification, revocation list, lockout, step-up, strict Pydantic v2 schemas implemented | [ ] | Code review record; endpoint declaration inventory |
| 3 | Security tests pass in CI: S1–S18 | [ ] | CI run URL for `tests/security/test_auth_*`; sentinel and grant-inspection reports |
| 4 | Audit: the seven named events emit and verify; A1–A5 pass | [ ] | `tests/auth/test_audit_events.py` report; event catalogue sample |
| 5 | Operations & compliance: classification applied, zero credential values in logs, residency register updated for identity data, alerts and metrics present | [ ] | Sentinel test output; residency register entry; alert catalogue |
| 6 | Deployment: image builds, scans clean of Critical findings, migration expand-and-contract, verified in Staging | [ ] | Build and scan reports; migration plan; Staging verification record |

## Gate sign-off & Verification Governance

| Stage | What is verified | Verifier (decision maker) | Approver | Pass policy |
|---|---|---|---|---|
| **CI / automated** | S9 credential sentinel, S10 grant inspection, S1 MFA enforcement, S3 family revocation, S12 cross-tenant `404` | CI pipeline (pytest) | Automated gate | Hard block on failure |
| **Gate 3 (Authentication)** | MFA cannot be bypassed by a direct API call; access tokens expire; refresh rotates and reuse revokes the family; a revoked session is refused before expiry; lockout with an audited release; step-up for the five named operations; RBAC `403`; recovery logged with login-level fidelity; no shared accounts | **Security Lead** | **CTO** | **No conditional pass for MFA or step-up** |
| **Independent compliance** | Audit-trail integrity, retention position, break-glass review, access baseline | Privacy Officer / Compliance Lead | External auditor (ISO 27001 / regulator) | Periodic and pre-launch |

**No self-approval.** The person who delivered the authentication work never signs Gate 3. The Security
Lead is the decision maker and the CTO the approver; where the deliverer holds either role, the gate is
signed by the other, and if neither is available the gate is **not signed** (`gates.md`; source `26 §4`).

> ## GATE 3 IS BLOCKED BY D-003
> The identity model is an open decision ([D-003](../../reference/decisions/D-003-identity-model.md)).
> Branch A (managed OIDC provider) conforms to the source contract and stores no password hash;
> Branch B (hardened self-hosted auth) is the repo as it exists. The evidence artefact, the failure
> modes and the residual risk differ materially between them, so **Gate 3 cannot be signed until
> D-003 closes**. Entry criteria also fail while the `users` shape is unresolved.
>
> **MFA and step-up permit no conditional pass.** Gate 3's only conditional-pass item is
> account-recovery logging, and only if the recovery path is disabled in the pilot, with an expiry and
> a compensating control. A conditional pass on MFA enforcement or step-up is not available at any
> level of approval.

## Control matrix rows fed by this module
| Requirement | Control | Implementation | Evidence | Owner | Status |
|---|---|---|---|---|---|
| MFA cannot be bypassed by a direct API call | MFA enforced in the token contract, not the UI | Central policy layer; `RequiresMFA`; strict schemas | S1, S14 | Security Lead | **OPEN — blocked by D-003** |
| Short-lived access tokens expire and are refused | Token expiry plus session lookup on every request | `core/security.py`; revocation list | S2, F5, F6 | Security Lead | **OPEN — blocked by D-003** |
| Refresh tokens rotate; reuse revokes the family | Single-use opaque tokens, `family_id` lineage, reuse detection | `refresh_tokens`; `session_revocations` | S3, F4 | Security Lead | **OPEN — blocked by D-003** |
| A revoked session is refused before expiry | Server-side deny list consulted per request | `session_revocations` | S4, F7, F8, S17 | CTO | **OPEN — blocked by D-003** |
| Lockout with an audited release path | Threshold counter plus privileged, step-up release | `login_attempts`, `account_lockouts` | S5, F9, F10 | Security Lead | **OPEN — blocked by D-003** |
| Step-up for the five named high-risk operations | Per-operation declaration; single-use resource-bound token | Central policy layer; step-up token | S6, S7, S15, F13 | Security Lead | **OPEN — blocked by D-003** |
| Account recovery is logged with login-level fidelity | Recovery events written at login fidelity | `auth.password_reset_*` | A1, A2, F11, F12 | Security Lead | **OPEN — blocked by D-003** |
| No shared accounts | One identity per person; access-review baseline | `users`; onboarding procedure | S8 | Security Lead | Planned |
| No credential value reaches any log, column, bundle or repository | `SECRET` containment; column grants; redaction filter; sentinel test | `clinos_auth` column grants; logger boundary | S9, S10, S18 | Security Lead | **OPEN — blocked by D-003** |

## Open items blocking Done
| Item | Owner | Status |
|---|---|---|
| **D-003** identity model: Branch A or Branch B — blocks the whole feature and Gate 3 | CTO + Security Lead | **OPEN** |
| Access-token lifetime 10 vs 15 minutes (OPEN-2) | Security Lead | OPEN |
| Lockout threshold 10 vs 5 failures (OPEN-3) | Security Lead | OPEN |
| Session table naming and revocation-list placement (OPEN-4) | CTO + Security Lead | OPEN |
| Five vs six step-up route families (OPEN-5) | CSO + Security Lead | OPEN |
| Signing-key custodian and rotation without invalidating live sessions (OPEN-8) | Security Lead | OPEN |
| Whether MFA must be phishing-resistant for all clinical roles | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Authentication-log retention per jurisdiction | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| IdP contract terms, residency and support access to identity data | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Verifier-hash classification reconciliation (`12 §5.1` vs `04 §3.11`) | Privacy Officer + Security Lead | OPEN |

## Sources
- `clinic-os-secure-by-design/24-definition-of-done.md`; `26-security-gates.md` §4; `27-security-testing.md` §2.1
- `clinic-os-secure-by-design/17-compliance-control-matrix.md` §4 (identity and access), §6
- `clinic-os-secure-by-design/06-authentication-rbac.md` §2, §3, §6, §8, §13, §14
- [`gates.md`](../../reference/gates.md) Gate 3; [`D-003`](../../reference/decisions/D-003-identity-model.md)
