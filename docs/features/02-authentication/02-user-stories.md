---
doc_id: FEAT-AUTH-02
title: Authentication, user stories
owner: Security Lead
status: DRAFT
last_reviewed: 2026-10-04
classification: RESTRICTED
related: 06-authentication-rbac, 26-security-gates, D-003
---

# Authentication: user stories

Each story carries a security criterion (S) and an audit criterion (A). Roles are the source's role
names (`06-authentication-rbac.md` §2, §9); no role has MFA optional and no shared account exists.

## Clinical user — Authorised Prescriber, Doctor, Nurse
**US-1 — Log in with MFA.** As a clinical user I want to log in with a second factor so my clinical
identity cannot be used with a stolen password alone.
- Acceptance: a valid first factor without a second factor creates no session; a successful second
  factor issues a short-lived access token and a rotating refresh token.
- S: MFA enforced by role in the token contract, not the UI; a first-factor-only session reaches only
  the enrolment screen and `GET /api/v1/auth/session`.
- A: `LOGIN_SUCCEEDED` with `actor_role`, `mfa_method`, `session_id_hash`, `source_ip`.

**US-2 — Fail a login and be locked out.** As a clinical user I want repeated failures to lock the
account so a password guess cannot continue indefinitely.
- Acceptance: at the defined failure count the account locks and further attempts are refused; the
  message is identical to a wrong credential.
- S: lockout enforced in the authentication path and the policy layer, never the UI; no whole-tenant
  lockout (doc 03 §4 login-DoS row).
- A: `LOGIN_FAILED` per attempt with `attempt_count`; `ACCOUNT_LOCKED` at the threshold.

## Any staff member
**US-3 — Have my sessions revoked when my credential changes.** As a staff member I want a credential
or MFA change to end my other sessions so a leaked token stops working.
- Acceptance: after a credential or MFA change, every other refresh family is refused; the acting
  session may continue only after re-authentication.
- S: revocation is server-side; a signed token is never trusted past the revocation lookup.
- A: `SESSION_REVOKED` per family with `reason` (`PASSWORD_CHANGE`, `MFA_CHANGE`).

**US-4 — Log out everywhere.** As a staff member I want to end every session on every device so a
shared or lost device cannot keep my access.
- Acceptance: `POST /api/v1/auth/logout-all` revokes every family for the user; the next refresh from
  any device returns `401`.
- S: tenant and user resolved from the session; a caller cannot revoke another user's sessions.
- A: `SESSION_REVOKED` per family plus the logout event, all with `request_id`.

## Administrator
**US-5 — Step up before changing access.** As an administrator I want a fresh factor before I change
user permissions so a stolen session cannot grant privilege.
- Acceptance: the permission change is refused with `403 step_up_required` until a fresh factor is
  presented; the step-up token is consumed and is bound to the operation and the target resource.
- S: permission change accepts a passkey or hardware key only — TOTP is excluded (doc 06 §8).
- A: `STEP_UP_SUCCEEDED` with `operation` and `resource_id`, then the permission-change event.

**US-6 — Release a lockout with a reason.** As an administrator I want to release a locked colleague
with a reason so they can work, and so the release is visible.
- Acceptance: release requires step-up and a reason code; the account becomes usable immediately.
- S: `users:manage` required; release never edits or deletes the failure history.
- A: `ACCOUNT_LOCKED` with `released_by` and `release_reason`; `login_attempts` rows stay append-only.

## Practice Owner
**US-7 — Step up before changing clinic security configuration.** As a practice owner I want a fresh
passkey before security settings change so the highest-blast-radius change is deliberate.
- Acceptance: the change is refused without fresh step-up; the old configuration remains in force.
- S: `tenant:configure` plus step-up; TOTP excluded; the tenant is resolved from the session.
- A: `STEP_UP_SUCCEEDED`, then `TENANT_SECURITY_CONFIG_CHANGED`.

## Compliance / Auditor
**US-8 — See that recovery happened.** As an auditor I want account recovery logged with the same
fidelity as login so the weakest link is evidenced.
- Acceptance: request, completion and failure each produce an event with `source_ip` and `request_id`;
  the response to the requester is identical whether or not the account exists.
- S: read-only; recovery cannot be performed by an auditor on another user; enrolment is required
  after recovery.
- A: `PASSWORD_RESET_REQUESTED` / `PASSWORD_RESET_COMPLETED` / failure, all with `result`.

## Security Lead
**US-9 — Revoke a suspected session now.** As a security lead I want to revoke a session immediately
so a suspected compromise is closed before token expiry.
- Acceptance: the session and its family are revoked; the access token is refused on the next request
  although `exp` has not passed.
- S: revocation is privileged and tenant-scoped; cross-tenant target returns `404`.
- A: `SESSION_REVOKED` with the revoking actor, target session hash and reason.

## Open items
| Item | Owner | Status |
|---|---|---|
| Whether a pharmacist identity is an interactive user or a service account in the MVP | Head of Product | OPEN |
| Whether a practitioner working across two clinics is two `users` rows or one identity with two tenant memberships | Engineering Lead + Clinical Safety Officer | OPEN |
| Whether the pilot operates without the recovery path (the only Gate 3 conditional-pass item) | CTO + Security Lead | OPEN |

## Sources
- `clinic-os-secure-by-design/22-user-stories.md` US-04, US-05; §5 matrix
- `clinic-os-secure-by-design/06-authentication-rbac.md` §2, §3, §5, §6, §8, §9, §13
- `clinic-os-secure-by-design/03-threat-model.md` §4
- `clinic-os-secure-by-design/26-security-gates.md` §4
