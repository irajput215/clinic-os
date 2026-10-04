---
doc_id: FEAT-AUTH-04
title: Authentication, threat model
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: threat model

## Method
Risk score is `Likelihood (1–5) × Impact (1–5)`, mnemonic and meaning per `03-threat-model.md` §2.
Residual bands: **Low ≤4** (accept with monitoring), **Medium 5–9** (treat this quarter, named test),
**High 10–16** (named treatment before release, Security Lead sign-off), **Critical ≥17** (release
blocker, CTO + CSO decision recorded). A residual of 5 or more is never accepted silently.

## STRIDE assessment and residual risk

| ID | STRIDE | Threat and attack path | Inherent | Control / mitigation | Residual | Owner | Source |
|---|---|---|:---:|---|:---:|---|---|
| **T-AUTH.1** | Spoofing | **Credential stuffing.** A breached credential list is replayed against `POST /api/v1/auth/login`. | High (4×3=12) | Breached-credential check, per-account/per-IP/per-tenant rate limits with backoff, MFA on every clinical and administrative role, distributed-attempt alerting | **Low (2×2=4)** | Security Lead | `03 §4; 02 §11` |
| **T-AUTH.2** | Spoofing | **MFA bypass by direct API call.** A hand-crafted request asserts `mfa=true`, `auth_time` or `acr` to reach a clinical route with one factor. | Critical (4×5=20) | `mfa` read only from the verified token or session record; strict Pydantic v2 schema rejects unknown fields; `RequiresMFA` declared centrally; enrolment-only session otherwise. Test `S1`, `S14` | **Low (1×4=4)** | Security Lead | `26 §4; 27 §2.1; 06 §2` |
| **T-AUTH.3** | Spoofing | **Stolen token replay.** An access token is lifted from a compromised endpoint and replayed. | High (4×4=16) | Short-lived access token, memory-only storage, session bound to the token `sid`, revocation list consulted per request, anomaly on new device fingerprint | **Medium (2×3=6)** | Security Lead | `03 §4; 02 §1 control 1` |
| **T-AUTH.4** | Spoofing | **Refresh-token reuse.** A rotated refresh token is replayed to mint a second live session. | High (3×4=12) | Opaque single-use token, `HttpOnly`/`Secure`/`SameSite=Strict` cookie, rotation on every use, **family revocation on reuse**, device-fingerprint binding, user notification | **Low (1×4=4)** | Security Lead | `03 §4; 27 §2.1; 06 §3` |
| **T-AUTH.5** | Elevation | **Session not revoked before expiry.** Logout, offboarding or role change leaves a valid token usable for the remaining token lifetime. | High (3×4=12) | Server-side deny list (`session_revocations`) plus `revoked_at` on the session, consulted on **every** request; offboarding revokes all families within 60 s; role change refuses refresh and forces a new login | **Low (1×4=4)** | CTO | `06 §3; 26 §4` |
| **T-AUTH.6** | Elevation | **Step-up bypass.** A high-risk operation is performed on an old session without presenting a fresh factor, or a step-up token is replayed on another resource. | Critical (4×5=20) | Step-up declared per operation server-side; token bound to user + session + operation + resource id; consumed on use; TOTP excluded for permission and security-configuration changes; failure audited | **Low (1×4=4)** | Security Lead | `06 §8; 26 §4; 27 §2.1` |
| **T-AUTH.7** | Spoofing | **Account-recovery abuse.** Helpdesk social engineering, or a forwarded reset link, resets the factor that protects the account. | High (3×5=15) | Single-use random token stored as a hash, 30 min expiry, bound to the requester's PKCE verifier; second factor required if enrolled; identical response for known and unknown accounts; step-up for MFA reset; recovery audited at login fidelity | **Medium (2×4=8)** | Security Lead | `03 §4; 06 §5; 27 §2.1` |
| **T-AUTH.8** | Information disclosure | **Credential storage compromise — the D-003 risk.** The database, a backup or an insider discloses credential material. Applies to Branch B; Branch A stores no verifier. | Critical (5×5=25) | **Branch A:** no credential value exists in any column, so there is nothing to disclose. **Branch B:** Argon2id with reviewed parameters and rehash-on-login, KMS-held pepper, verifier column readable only by `clinos_auth`, no credential in any log, bundle or repository — and the residual is genuinely higher because we now own the secret | **Branch A Low (1×2=2) / Branch B Medium (2×4=8)** | Security Lead | `02 §5.1; 12 §5.1; D-003` |
| **T-AUTH.9** | Information disclosure | **Account enumeration via login error differences.** Distinct messages, status codes or response timing reveal which addresses have accounts. | Medium (4×2=8) | One generic error body and status for wrong credential, locked account and unknown account; constant-time comparison; uniform failure path; both outcomes audited so the signal lives in the audit trail, not the response | **Low (1×2=2)** | Security Lead | `27 §2.1; 06 §6` |
| **T-AUTH.10** | Spoofing | **MFA fatigue or push bombing.** Repeated prompts until the user approves, or a real-time phishing proxy relays a TOTP code. | High (3×4=12) | Phishing-resistant authenticators preferred and [**REQUIRES LEGAL/REGULATORY VALIDATION** for clinical roles]; number matching only; prompt rate limits; alert on prompt volume per account; TOTP excluded from the two authorisation-changing operations | **Medium (2×4=8)** | Security Lead | `03 §4; 06 §2, §8` |
| **T-AUTH.11** | Tampering | **JWT confusion or algorithm substitution.** A forged token uses `alg: none`, a symmetric algorithm or an unexpected issuer key. | High (4×4=16) | Algorithm allow-list fixed to the issuer's key type, unknown `kid` rejected, `iss`/`aud`/`exp`/`nbf` all validated, JWKS cached with a bounded lifetime, no key material accepted from the request | **Low (1×4=4)** | Security Lead | `03 §4; 02 §1 control 1` |
| **T-AUTH.12** | Denial of service | **Login endpoint flood, or lockout weaponised.** An attacker locks a clinician out during a shift, or exhausts the auth path. | Medium (3×4=12) | WAF plus application rate limits, per-IP throttle with minimum 1 s spacing, **no whole-tenant lockout**, alert at 100 tenant failures/10 min, administrator release path with step-up, break-glass for clinical continuity | **Medium (2×3=6)** | Head of Platform | `03 §4; 06 §6` |
| **T-AUTH.13** | Repudiation | **A practitioner denies a high-risk action.** The actor claims they did not sign, dispatch or change permissions. | High (3×4=12) | Step-up captures actor, session, source IP, timestamp and role at decision time; append-only audit row written in the same transaction; hash chain over the export; role recorded as held at decision time, not later | **Low (1×4=4)** | Compliance Lead | `07 §1, §2, §10` |
| **T-AUTH.14** | Information disclosure | **Cross-tenant token or tenant confusion.** A valid tenant-A token is used against a tenant-B resource, or a forged `tenant_id` is supplied. | High (3×4=12) | Tenant resolved from the session and the resource, never the body; forged value rejected by the strict schema; RLS with `NULLIF` guard; **`404`, never `403`**; mismatch audited | **Low (1×4=4)** | Security Lead | `06 §1, §10; 05-tenant-isolation` |
| **T-AUTH.15** | Tampering | **Insider edits the session or revocation store.** A privileged operator rewrites `refresh_tokens` or deletes failure history to hide activity. | High (3×4=12) | App role is not the table owner and has no `BYPASSRLS`; `REVOKE DELETE, TRUNCATE` on sessions and attempts; column grants withhold the verifier and MFA seed; expiry purge runs as a separate `clinos_retention` role; grant-inspection test `S10` | **Low (1×4=4)** | Security Lead | `04 §3.11, §9; 07 §3` |

## Assumptions
- Identity is provided by a library or a managed provider, never hand-rolled — the whole model rests on
  this and it is exactly what **D-003** decides (`03 §1.2` assumption 1).
- Every tenant table has RLS enabled, forced, failing closed on an empty setting.
- The application role is not the table owner and holds no `BYPASSRLS`.
- No production credential or token material enters a lower environment.

## Open items
| Item | Owner | Status |
|---|---|---|
| Branch A or Branch B changes T-AUTH.8's residual band and the evidence artefact | CTO + Security Lead | **OPEN — D-003, blocks Gate 3** |
| Whether MFA must be phishing-resistant for all clinical roles (T-AUTH.10) | Security Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Confirm the lockout threshold, which changes T-AUTH.12's treatment (OPEN-3) | Security Lead | OPEN |
| Confirm the access-token lifetime, which bounds T-AUTH.3 and T-AUTH.5 (OPEN-2) | Security Lead | OPEN |

## Sources
- `clinic-os-secure-by-design/03-threat-model.md` §1.2, §2, §4, §12, §13
- `clinic-os-secure-by-design/06-authentication-rbac.md` §2, §3, §5, §6, §8, §10, §13
- `clinic-os-secure-by-design/02-security-architecture.md` §1 control 1, §5.1, §11
- `clinic-os-secure-by-design/26-security-gates.md` §4; `27-security-testing.md` §2.1
- `clinic-os-secure-by-design/07-audit-architecture.md` §1, §2, §3, §10
- [`D-003 identity model`](../../reference/decisions/D-003-identity-model.md)
