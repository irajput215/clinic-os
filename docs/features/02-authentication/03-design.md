---
doc_id: FEAT-AUTH-03
title: Authentication, design
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: design

## Identity and session tables — the D-003 fork
Branch A has **no credential column**; Branch B does. Everything else is shared. RLS is as for every tenant table: `ENABLE`/`FORCE ROW LEVEL SECURITY`, policy `tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, tenant set with `SET LOCAL` per transaction, app role not the owner and holding no `BYPASSRLS`.

| Table | Key columns | Branch | Note |
|---|---|:---:|---|
| `users` | `id`, `tenant_id`, `email`, `display_name`, `status`, `mfa_enrolled_at`, `last_login_at` | A and B | identity link, never a credential |
| `users`, branch column | `subject_id` = OIDC `sub` | **A** | conforms to the source contract |
| `users`, branch column | `hashed_password` (Argon2id) | **B** | the only credential column that exists |
| `refresh_tokens` | `id`, `tenant_id`, `user_id`, `token_hash`, `family_id`, `issued_at`, `expires_at`, `rotated_at`, `revoked_at`, `revoked_reason`, `auth_time`, `mfa_method`, `user_agent_hash`, `source_ip_hash` | A and B | `token_hash` is one-way; the token itself is never stored |
| `session_revocations` | `family_id`, `session_id`, `revoked_at`, `reason` | A and B | deny list consulted on every request |
| `mfa_enrolments` | `id`, `user_id`, `kind`, `secret`, `confirmed_at`, `recovery_code_hashes` | **B** | TOTP seed is `SECRET`, KMS-encrypted, read only by the auth path |
| `login_attempts` | `user_id`, `source_ip`, `attempted_at`, `outcome` | A and B | append-only counter source |
| `account_lockouts` | `user_id`, `locked_at`, `expires_at`, `released_at`, `released_by`, `release_reason` | A and B | the audited release path |

Naming diverges in the source: doc 06 §3 names `sessions(..., refresh_family_id, ...)`; doc 04 §3.11 names `refresh_tokens(..., family_id, ...)`; doc 02 §1 puts the revocation list inside `refresh_tokens`. This design follows doc 04 and records the divergence as **OPEN-4**.

## Token contract
| Claim | Source of truth | Rule |
|---|---|---|
| `iss` | IdP (A) / us (B) | pinned, exact match, no prefix matching |
| `aud` | our API client id | required; anything else refused |
| `exp`, `iat`, `nbf` | issuer | expiry enforced per request, independently of the session record; bounded clock skew only |
| `sub` | IdP `sub` (A) / `users.id` (B) | maps to exactly one `users` row in one tenant |
| `sid` | our session row | revocation lookup key — never logged |
| `jti` | issuer | replay detection, set on step-up tokens |
| `mfa` | IdP `amr`/`acr` (A) / `refresh_tokens.mfa_method` (B) | boolean; true only when a second factor was presented |
| `auth_time` | IdP (A) / our session record (B) | drives idle and step-up windows; server clock only |
| `tenant_id`, `roles` | our session record | tenant never from the body; roles advisory for the UI only, permissions recomputed per request |

**The client can never influence a claim that asserts MFA or freshness.** No endpoint accepts `mfa`, `auth_time`, `tenant_id`, `role` or `permissions` from a body, header or query string.

## MFA enforcement that a direct API call cannot bypass
1. A route declares `Authenticated`, `RequiresMFA` and `RequiresStepUp(<operation>)` in one place, the central policy layer. There is no per-handler boolean and no route that opts out silently.
2. `mfa` is read from the verified token, which the caller cannot mint: under Branch A it is IdP-signed, under Branch B it is written from the session record. A body, header or query parameter asserting MFA is rejected by the strict Pydantic v2 model (extra fields forbidden) and audited as a denial.
3. Before enrolment the only reachable routes are `GET /api/v1/auth/session` and the enrolment routes; everything else returns `403 mfa_enrolment_required`. SMS one-time codes are not acceptable for any role; provider push is acceptable only with number matching.

## Access tokens, refresh rotation and family revocation
- **Access token**: lifetime is configuration. doc 06 §3 says 10 minutes; doc 02 §1 and doc 03 §4 say 15 minutes — **OPEN-2**. Held in memory only, never in browser storage.
- **Refresh token**: opaque 32 random bytes, single-use, rotated on every use, stored only as `token_hash`, delivered in a `Secure`, `HttpOnly`, `SameSite=Strict` cookie scoped to `/api/v1/auth`.
- **Family revocation on reuse**: each refresh belongs to a `family_id`; a refresh consumes the presented token and issues a new one in the same family. Presenting a token whose `rotated_at` is set revokes the whole family, writes `AUTH_REFRESH_REUSE_DETECTED`, notifies the account holder and forces a new login. A refresh from a different device fingerprint than the family's creator is treated the same way.
- **Server-side revocation list**: `revoked_at`/`revoked_reason` on the session plus the `session_revocations` deny list, consulted on every request. A signed token cannot be un-signed, so revocation is a lookup, not a signature property.
- **Triggers**: logout, logout-all, credential change, MFA change or reset, role or permission change, offboarding, suspected compromise, IdP revocation event. Offboarding revokes everything within 60 s; the residual window is bounded by the access-token lifetime.
- **Timeouts**: idle 20 minutes clinical / 30 minutes administrative; absolute 12 hours from first authentication; maximum 3 concurrent sessions per user.

## Lockout and the audited release path
| Control | Threshold | Effect | Release |
|---|---|---|---|
| Failed logins per account | doc 06 §6: 10 in 15 min — doc 20 §2 / US-04 say **5** (**OPEN-3**) | lock 15 min, progressive to 60 min | successful authentication, or an administrator release with step-up |
| Failed logins per source IP | 20 in 10 min | throttle with exponential backoff, minimum 1 s between attempts | rolling window |
| Failed logins per tenant | 100 in 10 min | alert the Security Lead; per-IP throttle remains | rolling window |

Lockout is enforced in the authentication path and the policy layer, never in the UI. A locked account returns the same message as a wrong credential; the reason goes to the audit trail only. `login_attempts` is append-only, and every release requires step-up and a reason code and writes `ACCOUNT_LOCKED` with `released_by` and `release_reason`.

## Step-up for the five named high-risk operations
| # | Operation | Endpoint | Factor | Window | Audit |
|:--:|---|---|---|---|---|
| 1 | Prescription sign | `POST /api/v1/prescriptions/{id}/sign` | passkey, hardware key or TOTP | 2 min, single use | `STEP_UP_SUCCEEDED` |
| 2 | Prescription dispatch | `POST /api/v1/prescriptions/{id}/dispatch` | passkey, hardware key or TOTP | 2 min, single use | `STEP_UP_SUCCEEDED` |
| 3 | Bulk patient export | `POST /api/v1/reports/export` | as above plus a typed reason | 5 min, single use | `STEP_UP_SUCCEEDED` |
| 4 | Change user permissions | `POST /api/v1/users/{id}/permissions`, `PUT /api/v1/roles/{id}/permissions` | passkey or hardware key only | 5 min, single use | `STEP_UP_SUCCEEDED` |
| 5 | Change tenant security configuration | `PUT /api/v1/tenants/{id}/security-config` | passkey or hardware key only | 5 min, single use | `STEP_UP_SUCCEEDED` |
| **+** | **Sixth route family the source also requires** | `POST /api/v1/users/{id}/mfa-reset` and break-glass elevation | passkey or hardware key plus a ticket reference | 5 min, single use | `AUTH_MFA_RESET` / `AUTH_BREAK_GLASS_GRANTED` |

Doc 20 §2, ADR-006 and Gate 3 say **five**; doc 06 §8 lists **six** rows. The sixth is a route *family* (MFA reset plus break-glass), not a sixth clinical operation. All six are enforced; the count divergence is **OPEN-5**. A step-up token is bound to user + session + operation + resource id, consumed on use, refused on a different resource, and a failure is audited `AUTH_STEP_UP_FAILED`. TOTP is excluded from operations 4 and 5 because a real-time phishing proxy can relay a TOTP code.

## Database privileges
`clinos_app` is not the table owner and holds no `BYPASSRLS`; the credential path connects as `clinos_auth`; the expiry purge as `clinos_retention`.

```sql
-- audit: append-only by grant, never by convention
GRANT SELECT, INSERT ON audit_log TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
-- sessions: rotate and revoke, never delete
GRANT SELECT, INSERT, UPDATE ON refresh_tokens TO clinos_app;
REVOKE DELETE, TRUNCATE ON refresh_tokens FROM clinos_app;
GRANT DELETE ON refresh_tokens TO clinos_retention;          -- expiry purge only
-- lockout: append-only attempts, mutable lockout state
GRANT SELECT, INSERT ON login_attempts TO clinos_app;
REVOKE UPDATE, DELETE, TRUNCATE ON login_attempts FROM clinos_app;
GRANT SELECT, INSERT, UPDATE ON account_lockouts TO clinos_app;
-- Branch A: no credential column to protect
REVOKE ALL ON users FROM clinos_app;
GRANT SELECT (id, tenant_id, subject_id, email, display_name, status, mfa_enrolled_at, last_login_at) ON users TO clinos_app;
-- Branch B: only the credential path may read or write the verifier
REVOKE SELECT (hashed_password) ON users FROM clinos_app;    -- column-level: SELECT * now fails
GRANT SELECT (id, tenant_id, hashed_password, mfa_enrolled_at), UPDATE (hashed_password) ON users TO clinos_auth;
GRANT SELECT (id, user_id, kind, confirmed_at) ON mfa_enrolments TO clinos_app;
REVOKE SELECT (secret), SELECT (recovery_code_hashes) ON mfa_enrolments FROM clinos_app;
GRANT SELECT (user_id, secret, confirmed_at), INSERT, UPDATE (confirmed_at) ON mfa_enrolments TO clinos_auth;
```

Column-level grants do not apply to `SELECT *`, so auth queries enumerate columns. The app role cannot read the verifier column or the MFA seed on any path. Under Branch A the Branch-B statements are never applied, because `hashed_password` does not exist — that is the D-003 fork in the migration.

## Endpoints
| Method and path | Auth | MFA | Permission | Step-up | Notes |
|---|:---:|:---:|---|:---:|---|
| `GET /api/v1/auth/authorize` | no | — | — | — | Branch A: PKCE redirect, state + nonce, one registered redirect URI |
| `POST /api/v1/auth/login` | no | — | — | — | Branch B: credential + second factor; generic failure |
| `POST /api/v1/auth/callback` | no | — | — | — | Branch A: code + PKCE verifier; verify JWKS, `iss`, `aud`, `exp` |
| `POST /api/v1/auth/refresh` | cookie | — | — | — | rotate; reuse revokes the family |
| `POST /api/v1/auth/logout`, `POST /api/v1/auth/logout-all` | yes | yes | — | — | revoke this family, or every family for the user |
| `POST /api/v1/auth/step-up` | yes | yes | — | — | issue a single-use resource-bound step-up token |
| `POST /api/v1/auth/recover`, `POST /api/v1/auth/recover/complete` | no | — | — | — | identical response whether the account exists; single-use hashed token, 30 min, second factor if enrolled |
| `POST /api/v1/auth/mfa/enrol`, `POST /api/v1/auth/mfa/verify` | yes | no | — | — | Branch B enrolment-only session |
| `GET /api/v1/auth/session` | yes | no | - | - | the only pre-MFA route. The advisory UI capabilities are `GET /api/v1/users/me/permissions` (feature 03; owner decision 2026-10-07) |
| `POST /api/v1/users/{id}/mfa-reset` | yes | yes | `users:manage` | yes | privileged reset; audited |
| `GET /api/v1/auth/jwks.json` | no | — | — | — | Branch B only; public keys, never secrets |

## Deny-by-default request path
1. Edge: TLS, HSTS, per-IP rate limit; nothing reaches code unthrottled.
2. Credential present? No → `401`, fail closed, audited. If present, verify signature against the pinned key set and an algorithm allow-list, and validate `iss`, `aud`, `exp`, `nbf`; unknown `kid` or `alg` → `401`.
3. Load the session row and consult the server-side revocation list → `401` even before `exp`.
4. Check enrolment and the `mfa` claim; not enrolled → only `GET /api/v1/auth/session` and enrolment, everything else `403 mfa_enrolment_required`.
5. Resolve `tenant_id` from the session, never the body; tenant must be `ACTIVE`; `SET LOCAL app.tenant_id` inside the transaction.
6. Central policy layer: `can(actor, permission, resource)`; cross-tenant resource → `404`, permission not held → `403`.
7. Step-up required? Fresh `auth_time` or a step-up token bound to user + session + operation + resource; consume it; otherwise `403 step_up_required`.
8. Audit intent, and every denial, with the full envelope **before** the state change, in the same transaction.
9. Validate the body against a strict Pydantic v2 model — extra fields forbidden — then execute in one transaction; an audit write failure aborts the action.

## Failure behaviour
- Any error resolving identity, tenant or authorisation denies. There is no "continue unscoped".
- Errors use the envelope `{"error": {"code", "message", "request_id", "details"}}`; no stack trace, no credential, no account-existence hint.
- A locked account, a wrong password and an unknown account return the same body and the same latency class.
- IdP outage (Branch A): existing sessions run to their token lifetime, no new login, degradation to read-only — never fail-open (doc 20 §2). An unavailable audit store fails the auth action `503`.

## Open items
| # | Item | Owner | Status |
|---|---|---|---|
| OPEN-2 / OPEN-3 | Access-token lifetime 10 vs 15 minutes; lockout threshold 10 vs 5 failures | Security Lead | OPEN |
| OPEN-4 | Session table naming (`sessions` vs `refresh_tokens`) and revocation-list placement | CTO + Security Lead | OPEN |
| OPEN-5 | Five vs six step-up route families | CSO + Security Lead | OPEN |
| OPEN-8 | Signing-key custodian and rotation without invalidating live sessions | Security Lead | OPEN — D-003 item 5 |

## Sources
- `clinic-os-secure-by-design/06-authentication-rbac.md` §1–§6, §8, §10, §12, §13, §14; `02-security-architecture.md` §1 control 1, §2, §5.1, §6, §11
- `clinic-os-secure-by-design/03-threat-model.md` §4; `04-database-erd.md` §3.2, §3.11; `21-technical-design.md` §4, §7
- `clinic-os-secure-by-design/12-data-classification.md` §5.1; `20-product-requirements.md` §2; `25-adr/ADR-006-authentication-architecture.md`
- [`D-003 identity model`](../../reference/decisions/D-003-identity-model.md)
