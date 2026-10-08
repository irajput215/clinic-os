# ADR-F002: Token storage and the interim step-up for signing

- **Status:** Accepted (interim, until D-003 identity model)
- **Date:** 2026-10-06

## Context

The API issues a 15-minute HS256 access token from `POST /login/access-token` and has no refresh
token (D-003 is open on managed OIDC vs self-hosted; MFA and refresh rotation are blocked behind
it). The template UI this app replaced kept the token in `localStorage`.

Signing a prescription needs step-up authentication. No step-up endpoint exists.

## Decision

1. Keep the token in **`sessionStorage`**. It is scoped to one tab, cleared when the tab closes, and
   never shared with another tab or a later visit. That is strictly narrower exposure than
   `localStorage` for the same XSS threat. Every access is wrapped so blocked storage degrades to
   "session ends on reload" instead of an error.
2. Sign-out clears the token and the query cache (and, until [ADR-F006](ADR-F006-preview-store-retired.md) retired it, the preview store).
3. **Interim step-up:** the Review and sign dialog requires the password, re-authenticates against
   `POST /login/access-token`, and only then signs. A wrong password is refused by the server; the
   login endpoint is rate limited.

## Target (when D-003 lands)

The target is an httpOnly, `Secure`, `SameSite=Strict` refresh cookie with rotation and
family revocation, the access token held in memory only, and step-up via TOTP/WebAuthn on a
dedicated endpoint whose proof the sign call requires server-side. The UI changes are confined to
`lib/session.ts` and the sign dialog.

## Consequences

- A tab close ends the session. That's acceptable for clinical workstations, and arguably desirable.
- The interim step-up proves the password, not a second factor. It is recorded here as not
  meeting the MFA requirement, so nobody mistakes it for that.

## Update 2026-10-07: the interim step-up is server-side

Decision 3 no longer re-runs `POST /login/access-token` in the browser. The password is re-proved by
`POST /api/v1/auth/step-up` (`backend/app/modules/identity_tenancy`), which stores only the SHA-256 of
a random token bound to the user, the operation (`prescription.sign` or `prescription.dispatch`) and
the script id, valid two minutes. The sign and dispatch transactions spend it once with a conditional
`UPDATE`; a missing, spent, expired or mismatched grant is `403 STEP_UP_REQUIRED` and audited
`auth.step_up_failed`. When D-003 lands, only the factor checked by that endpoint changes. It is still
not MFA (audited `mfa_method = PASSWORD_REENTRY`).
