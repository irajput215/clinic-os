---
doc_id: FEAT-AUTH-01
title: Authentication, requirements
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: requirements

## Purpose
Prove who is acting, prove it strongly enough for clinical work, and make that proof revocable at every
moment it matters. Authentication is the control every other control assumes: tenant isolation, the
audit trail and the prescription safety gate all trust the identity this module asserts.

The module answers one question for the rest of the platform: **which human is this, in which tenant,
holding which roles, and how long ago did they last present a second factor?**

## The identity model is an OPEN decision (D-003)
The source contract mandates a managed OIDC provider and states *"we store no password hash"*. This repo
ships `PyJWT` + `pwdlib[argon2,bcrypt]` password auth. Both branches are live; **neither is chosen**.
**Gate 3 cannot be signed until D-003 closes.** No requirement below assumes a branch; where the shape
differs it is stated per branch.

| | Branch A — managed OIDC provider (source contract) | Branch B — self-hosted password auth, hardened (repo as it exists) |
|---|---|---|
| Credential authority | IdP; ClinOS stores no password verifier | ClinOS; Argon2id verifier in `users.hashed_password` |
| Identity key | `users.subject_id` = OIDC `sub` | `users.id` plus a local credential |
| `mfa` / `auth_time` claims | Issued by the IdP, verified by us | Minted by us from our session record |
| MFA implementation | IdP policy plus our enforcement check | TOTP enrolment, recovery codes, our check |
| Lockout | IdP policy; we mirror the event | `login_attempts` + `account_lockouts` tables |
| Account recovery | IdP recovery; we audit the outcome | Our single-use hashed reset token |
| Step-up | Fresh IdP `auth_time` / `acr` re-verification | Our single-use step-up token |
| Revocation | IdP revocation event plus our deny list | Our refresh-token family plus deny list |
| Source conformance | Conforms | **Diverges** — needs D-003 `Accepted` + compensating control |
| Blast radius if credentials leak | The provider's | Ours: verifier column, pepper and key management |
| Cost | IdP contract; residency and vendor register (Gate 5) | We own storage, MFA, recovery, lockout forever |

Whichever is chosen, R1–R14 and the Gate 3 checks are identical. Only the artefact that proves them
differs.

## Requirements

| ID | Requirement | Testable acceptance |
|---|---|---|
| **R1** | Every protected endpoint requires an authenticated session | No token returns `401`; no route has an unconditional branch |
| **R2** | MFA is enforced server-side for every clinical and administrative role | A first-factor-only session reaches only enrolment and `GET /api/v1/auth/session`; a client-asserted `mfa` claim is refused |
| **R3** | Access tokens are short-lived and refused after expiry | Expired token returns `401` with no data |
| **R4** | Refresh tokens are opaque, single-use and rotated on every use | Two refreshes return different tokens; the first is rejected afterwards |
| **R5** | Reuse of a rotated refresh token revokes the whole family | Replay revokes the family and audits `AUTH_REFRESH_REUSE_DETECTED` |
| **R6** | Revocation is server-side and effective before token expiry | After logout or offboarding, a still-valid access token is refused within 60 s |
| **R7** | Idle and absolute timeouts apply by role class | Clinical idle 20 min, administrative 30 min, absolute 12 h, maximum 3 concurrent sessions |
| **R8** | Lockout after the defined failure count, with an audited release path | Threshold reached locks the account and returns the generic message; every release writes an event naming the releasing actor |
| **R9** | Step-up is enforced server-side for the five named high-risk operations | Operation without fresh step-up returns `403` plus a challenge; nothing is performed |
| **R10** | Account recovery is logged with login-level fidelity | Request, completion and failure each emit an event with `source_ip` and `request_id`; the response is identical whether or not the account exists |
| **R11** | No shared accounts, and no credential material in any log, column, bundle or repository | Access-review baseline shows one identity per person; sentinel test finds zero credential values in every log sink |
| **R12** | Cross-tenant authentication context returns `404`, never `403` | A valid tenant-A token requesting a tenant-B resource gets `404` |
| **R13** | Denied and failed attempts are audited with the same fidelity as successes | Every `401`/`403` on an auth route writes an event carrying the outcome |
| **R14** | The frontend can neither enforce nor grant access | A hand-crafted request with the correct body and no session is refused exactly as a UI-originated one |

## Out of scope for the MVP
- SAML federation as the primary path (doc 06 §1 rejects it; a tenant contract that mandates SAML is a
  commercial conversation, not an architecture change).
- Patient-facing authentication (doc 06 O6 — **REQUIRES LEGAL/REGULATORY VALIDATION**).
- Social or consumer identity, and clinician self-registration.
- Hardware-key issuance, shipping and physical token logistics.
- Non-interactive service-account authentication beyond a scoped, rotating machine credential
  (`02-security-architecture.md` §6; owned by 13-integration-boundaries).

## Open items
| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-1 | Identity model: Branch A or Branch B ([D-003](../../reference/decisions/D-003-identity-model.md)) | CTO + Security Lead | **OPEN — blocks Gate 3** |
| OPEN-2 | Access-token lifetime: doc 06 §3 = 10 min vs doc 02 §1 / doc 03 §4 = 15 min | Security Lead | OPEN — `25-adr/ADR-006-authentication-architecture.md` F2 |
| OPEN-3 | Lockout threshold: doc 06 §6 = 10 failures in 15 min vs doc 20 §2 / US-04 = 5 failures | Security Lead | OPEN — ADR-006 F3 |
| OPEN-4 | Must MFA be phishing-resistant for all clinical roles, or only privileged ones? | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-5 | Step-up window: doc 06 §8 = 2 min for sign and dispatch vs D-003 Option B = 5 min single-purpose | Clinical Safety Officer + Security Lead | OPEN — ADR-006 F4 |
| OPEN-6 | IdP contract terms, residency and support access to identity data | CTO + Compliance Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| OPEN-7 | Authentication-log and session retention per jurisdiction | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |

## Sources
- `clinic-os-secure-by-design/06-authentication-rbac.md` §1–§6, §8, §12, §13, §14
- `clinic-os-secure-by-design/02-security-architecture.md` §1 control 1, §2, §5.1, §6, §11
- `clinic-os-secure-by-design/03-threat-model.md` §4
- `clinic-os-secure-by-design/20-product-requirements.md` §2; `22-user-stories.md` US-04
- `clinic-os-secure-by-design/26-security-gates.md` §4; `27-security-testing.md` §2.1
- [`D-003 identity model`](../../reference/decisions/D-003-identity-model.md); [`gates.md`](../../reference/gates.md) Gate 3
