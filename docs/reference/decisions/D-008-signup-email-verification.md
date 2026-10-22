# D-008: Organisation signup is verified by email and does not disclose which addresses have accounts

- **Status:** Accepted (engineering decision, 2026-10-08; for owner review with Milestone 4)
- **Date:** 2026-10-08
- **Owner:** CTO
- **Supersedes:** the recorded residual risk in `register_user` (`backend/app/api/routes/users.py`)
  and `docs/progress.md` ("a taken email is answered `400`, which discloses that the address has an
  account")
- **Related:** `docs/features/02-authentication/04-threat-model.md` T-AUTH.9 (account enumeration),
  `docs/features/03-users-and-roles/04-threat-model.md` T-03.8, `docs/reference/business-flow.md`
  step 1, `docs2/sdlc/01-auth-and-shell/api.md`

## Context

`POST /api/v1/users/signup` created the organisation, the account and the Practice Owner grant at once
and the app signed the person straight in. An address that already had an account was answered
`400 "already exists"`, so anyone could ask the API which addresses hold a Clinic OS account (a list
of clinic owners and staff). The answer could not simply be made uniform while signup signed its owner
in: a new address succeeds and can sign in, a taken one cannot. Removing the signal needs the account
to be proven before it exists, which is email verification.

## Decision

### 1. One answer for every address

`POST /users/signup` answers `202 {request_id, expires_in_hours}` whether or not the address has an
account, and does the same work on both paths, in one transaction, before it answers:

| Step | New address | Address that has an account |
|---|---|---|
| Look the address up (case-insensitively) | one `SELECT` | one `SELECT` |
| Argon2 hash | of the chosen password | of a random secret (same cost; the result is discarded) |
| Write | one `signup_requests` row (with the hash) | one `signup_requests` row (no hash: it can never be verified) |
| Purge expired requests | one `DELETE` | one `DELETE` |
| Email | the verification link | a notice: "someone tried to register with this address; sign in or reset your password" |

Status, body and headers are identical. The timing class is the same because the statements, the
hash and the one outgoing message are the same; the two emails differ only in their text. Nothing
in the response depends on the address. What remains is the difference between rendering two
similar templates (microseconds), far inside the noise of one database round trip (~216 ms in
production) and one SMTP submission. A uniform answer is also given for a deactivated account (it
still holds the address). `request_id` is a random identifier of this one attempt, returned to the
person who made it; it names no account and cannot be used to look one up.

### 2. The organisation is created on verification, not before

A signup writes only a `signup_requests` row: no `tenants` row, no `user` row, no grant. The link
(`{FRONTEND_HOST}/verify-email?token=...`) opens a page with one button, "Confirm and sign in";
`POST /users/signup/verify` then creates the organisation, the account and the Practice Owner grant in
one transaction (exactly what signup did before), writes `user.create` in the new tenant's audit log,
deletes every `signup_requests` row for that address, and answers an access token, so the person is
signed in.

**Why not an inactive organisation and account at signup:** an unverified account would hold the
address, so a second signup by the real owner would have to be refused (an enumeration signal again)
or overwrite the first (an attacker's password). It would also leave tenants that nobody can use and
nobody owns. With nothing created until verification there is nothing to clean up, sign-in needs no
new "unverified" state (an unverified person simply has no account, and sign-in says "Incorrect email
or password" as for any unknown address), and the frozen login route is untouched.

**Why a button and not automatic verification on page load:** mail scanners that open links would
otherwise spend the link (and receive a session).

### 3. A second signup for an unverified address is a second, independent request

Each signup is its own request, with its own password and its own link, and the first one to be
verified creates the account; the others are then refused like a spent link. A later signup never
changes an earlier request.

**Why:** the pre-registration attack. If a second signup reused or replaced the first, an attacker who
signs up first with a victim's address and a password of their choosing would get the victim's own
verification click to activate the attacker's password. Independent requests mean a verified account
always carries the password of the person who opened their own link.

### 4. Unverified signups expire

The link and its request expire after `SIGNUP_VERIFICATION_EXPIRE_HOURS` (default 24). Expired
requests are deleted by the next signup (`DELETE ... WHERE expires_at < now()`), so a pending password
hash lives at most until the expiry plus the next signup. `POST /users/signup/resend {request_id}`
sends the same request's email again with a fresh link (the previous link is refused from then on)
and restarts the window; it answers `202` whatever the id, sends nothing for an unknown, expired or
used one, and stops sending after 5 emails per request (`send_count`), so it cannot be used to flood
a mailbox. A notice request is resent as a notice.

### 5. No outgoing mail: signup fails closed

Without SMTP (`settings.emails_enabled` false) signup is refused `503 EMAIL_NOT_CONFIGURED`, the
invitation's pattern, before anything is written: an account nobody can verify is never created.
This check depends only on configuration, so it discloses nothing about an address.

### 6. Where the code lives

`docs/reference/build-contract.md` §7 gives `users_roles` the user lifecycle and every
`/api/v1/users/*` route. The route therefore moves out of the frozen legacy file into
`backend/app/modules/users_roles/router.py` (`signup_router`, same path and operation id, so the
SDK's `registerUser` keeps its name); the logic is `users_roles.signup`. The legacy `register_user` is
deleted rather than left as a second route. `create_tenant_for_signup` stays in `identity_tenancy`
and is called through its service facade.

### 7. Rate limits

Per client address, as signup was: `signup` 20/min, `signup-resend` 20/min, `signup-verify` 20/min
(each its own window). The link is a signed, purpose-bound token with 256 bits of key behind it, so
the verify limit bounds load rather than guessing.

## Consequences

- Controls changed: a new platform-level table `signup_requests` (no tenant exists yet, so no
  `tenant_id` and no RLS, like the legacy `user` table it precedes); three routes; two emails; a new
  `user.create` event at verification (no new action); three rate-limit windows.
- Signup now depends on outgoing mail in every environment, including local development (Mailpit,
  `compose.yml`) and CI.
- `scripts/measure-production.py` cannot read the probe's mailbox: it registers the probe once and
  tells the operator to open the emailed link; after that it signs in as before
  (`docs/reference/performance.md`).
- The e2e suite completes verification through Mailpit (`frontend/tests/accounts.ts`).
- Open: whether verifying should also be required for a password change of an address (out of scope),
  and whether the notice email should be rate limited per address beyond the per-client limits
  (today: no; the per-client limit and the per-request cap bound it).
