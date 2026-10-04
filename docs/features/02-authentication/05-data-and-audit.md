---
doc_id: FEAT-AUTH-05
title: Authentication, data and audit
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: data and audit

## Classification levels
Seven levels, from `12-data-classification.md` §1. The ladder is a containment ladder: each level is a
superset of the controls above it.

`PUBLIC` < `INTERNAL` < `CONFIDENTIAL` < `SENSITIVE` < `HEALTH_INFORMATION` < `HIGHLY_SENSITIVE` < `SECRET`

## Fields and classification
| Field | Level | Log | Audit | Analytics | Non-prod | Notes |
|---|---|:---:|:---:|:---:|:---:|---|
| `users.id`, `tenant_id`, `status` | INTERNAL | yes | yes | aggregate only | synthetic | identifiers and state only |
| `users.email`, `display_name` | SENSITIVE | never | yes | never | synthetic | workforce personal information |
| `users.subject_id` (Branch A) | CONFIDENTIAL | never | action only | never | synthetic | OIDC `sub`; a stable external identifier |
| `users.mfa_enrolled_at`, `mfa_state` | SENSITIVE | yes | yes | never | synthetic | security posture, no factor value |
| `users.hashed_password` (Branch B only) | **SECRET-grade** | never | never | never | never | see the reconciliation note below |
| `mfa_enrolments.secret` | **SECRET** | never | never | never | never | TOTP seed; KMS-encrypted; never in a log, bundle or repo |
| `mfa_enrolments.recovery_code_hashes` | SENSITIVE | never | never | never | never | one-way hashes |
| `refresh_tokens.token_hash` | SENSITIVE | never | never | never | never | one-way; doc 04 §3.11 calls it SECRET — see Open items |
| `refresh_tokens.family_id`, `auth_time`, `mfa_method` | INTERNAL | never | action only | never | synthetic | `sid`/family are never logged |
| `refresh_tokens.user_agent_hash`, `source_ip_hash` | SENSITIVE | never | action only | never | synthetic | hashed for minimisation |
| `login_attempts.*` | SENSITIVE | never | action only | aggregate only | synthetic | failure metadata |
| `account_lockouts.*` | SENSITIVE | yes | yes | aggregate only | synthetic | lockout state and release provenance |
| Access tokens, refresh tokens, step-up tokens, auth codes, PKCE verifiers | **SECRET** | never | never | never | never | in memory or an `HttpOnly` cookie only |
| JWT signing keys, KMS plaintext data keys, OIDC client secret | **SECRET** | never | never | never | never | KMS/Secrets Manager; referenced by ARN |
| Session identifiers (`sid`) and refresh-family identifiers | SENSITIVE | never | action only | never | synthetic | fixation and correlation risk if logged |

**Hard rule for `SECRET`.** A password verifier, an MFA seed, a signing key or a session secret never
appears in **any log, any application database column, any frontend bundle or any repository**. A
secret found in a log sink, a bundle, a container image or a Git object is an incident under
`18-incident-response.md` R3, not a cleanup task. A one-way hash stored for verification is classified
`SENSITIVE` by `12-data-classification.md` §5.1 rule 1 — but the verifier hash and the MFA seed receive
the full `SECRET` control set here, and the two classifications are reconciled in Open items.

## Branch-dependent residue
| Branch | Credential material at rest | Residency of identity data |
|---|---|---|
| A — managed OIDC provider | None in ClinOS. `users` has no credential column; the IdP holds the verifier | The IdP's region is a vendor-register entry; **REQUIRES LEGAL/REGULATORY VALIDATION** |
| B — hardened self-hosted | `users.hashed_password` (Argon2id) and `mfa_enrolments.secret` (KMS-encrypted) | Australia (`ap-southeast-2`), one region only |

Under Branch A the Branch-B rows above simply do not exist. That is the D-003 fork expressed in data.

## Audit event catalogue
| Event (source name) | Repo action | Trigger | Key fields beyond the envelope |
|---|---|---|---|
| `LOGIN_SUCCEEDED` | `auth.login` | successful authentication | `actor_role`, `mfa_method`, `session_id_hash`, `source_ip` |
| `LOGIN_FAILED` | `auth.login_failed` | any failed authentication | `actor_role` where known, `reason`, `source_ip`, `attempt_count` |
| `MFA_CHALLENGE_FAILED` | `auth.mfa_challenge_failed` | wrong or expired second factor | `actor_role`, `method`, `reason`, `source_ip` |
| `ACCOUNT_LOCKED` | `auth.account_locked` | threshold reached, or a release | `attempt_count`, and on release `released_by`, `release_reason`, `step_up` |
| `STEP_UP_SUCCEEDED` | `auth.step_up` | successful fresh factor for a named operation | `actor_role`, `operation`, `resource_id`, `mfa_method` |
| `SESSION_REVOKED` | `auth.session_revoked` | logout, logout-all, offboarding, credential/MFA/role change, suspected compromise | `session_id_hash`, `family_id_hash`, `reason`, `revoked_by` |
| `AUTH_BREAK_GLASS_GRANTED` | `auth.break_glass_granted` | break-glass elevation granted | `actor_role`, `ticket_reference`, `expires_at`, `step_up` |

Also emitted and required by the source: `auth.logout`, `auth.step_up_failed`,
`auth.password_reset_requested`, `auth.password_reset_completed`, `auth.refresh_reuse_detected`,
`auth.mfa_reset`. Two naming systems are in use: doc 20 §2 and doc 06 use `SCREAMING_SNAKE`; doc 07 §1
uses lowercase dot form. Doc 07 §1's table has no `ACCOUNT_LOCKED` and no break-glass action. The
divergence is recorded as OPEN-9; the repo emits the lowercase dot action and carries the source name
in the event catalogue table above.

## Event envelope
Every event uses the doc 07 §2 envelope, written in the same transaction as the change:

`event_id, timestamp, tenant_id, actor_id, actor_role, action, resource_type, resource_id, result,
reason, source_ip, request_id, correlation_id, prev_hash, hash`

- `tenant_id` comes from the request context, never the body. `actor_role` is the role held at decision
  time, not later.
- `resource_type` for this module is `SESSION` for login, logout, step-up and revocation events.
- `reason` is a controlled code, not free text. A credential, token, session identifier or family
  identifier is never an envelope value.
- `result` is `SUCCESS`, `DENIED`, `FAILED` or `UNKNOWN`.
- **Denied and failed attempts are audited with the same fidelity as successes.** An
  `AUTHZ_DENIED_CROSS_TENANT` or `AUTH_STEP_UP_FAILED` event is written before the response leaves.
- An audit write failure aborts the authentication action (fail closed, `503`).

## Retention and deletion
Status: OPEN — **REQUIRES LEGAL/REGULATORY VALIDATION** with the Privacy Officer / Regulatory Lead.

Working assumption for design only, from `14-retention-and-deletion.md`: 12 months recommended for
authentication, authorisation and access events; 12 months recommended for authentication records and
sessions. Doc 04 §3.11 says `refresh_tokens` rows are hard-deleted after expiry plus a grace period,
which conflicts with the 12-month recommendation — recorded as OPEN-10. Audit events are removed only
by whole-partition expiry after the retention period, never by row deletion, and a legal hold suspends
expiry.

## Open items
| Item | Owner | Status |
|---|---|---|
| Verifier hash classification: `12 §5.1` rule 1 says SENSITIVE (one-way hash); `04 §3.11` marks `token_hash` SECRET and this doc applies the SECRET control set | Privacy Officer + Security Lead | OPEN — doc 12 §5.1 reconciliation |
| Event-naming divergence and the missing `ACCOUNT_LOCKED` / break-glass actions in `07 §1` | Security Lead + Compliance Lead | OPEN |
| Session-row retention: hard delete after expiry (`04 §3.11`) vs 12 months recommended (`14`) | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |
| Authentication-log retention per jurisdiction | Regulatory Lead | REQUIRES LEGAL/REGULATORY VALIDATION |
| Identity-data residency and support access for the chosen provider | Privacy Officer | REQUIRES LEGAL/REGULATORY VALIDATION |

## Sources
- `clinic-os-secure-by-design/12-data-classification.md` §1, §2, §3 (audit/identity/sessions), §4, §5.1
- `clinic-os-secure-by-design/07-audit-architecture.md` §1, §2, §3, §7, §9, §10
- `clinic-os-secure-by-design/04-database-erd.md` §3.2, §3.11
- `clinic-os-secure-by-design/14-retention-and-deletion.md`; `13-data-residency.md`
- `clinic-os-secure-by-design/20-product-requirements.md` §2 (audit requirements)
- `clinic-os-secure-by-design/15-privacy-impact-assessment.md`
