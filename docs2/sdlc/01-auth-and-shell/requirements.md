# Auth and app shell: requirements

**For:** Every staff member: practice principal, contractor GPs, nurses, practice manager, reception.

## User stories

- As a clinician, I sign in with my email and password and land where I was going.
- As a clinician, I can see the whole practice at a glance from a grouped sidebar with live counts.
- As a clinician, I can jump to any patient by typing part of their name.
- As a practice manager, I know that signing out on a shared workstation leaves nothing behind.

## Functional requirements

- R1 Sign-in posts to `POST /login/access-token`. A failure says only that the email and password don't match an active account.
- R2 Unauthenticated access to any staff route redirects to `/login?redirect=<path>`. Only same-origin paths are honoured.
- R3 A `401` from any call signs out once and returns to sign-in with the current path as `redirect`.
- R4 A `403` never signs out. The screen says the action isn't available to the role.
- R5 The sidebar groups Care / Prescribing / Business / Practice. Items not in this phase are visibly disabled.
- R6 The script queue and approvals items show live counts of items needing action.
- R7 Patient quick-find filters the loaded patients in memory. Nothing typed is sent or put in a URL.
- R8 Sign-out clears the token, the query cache and the preview store.
- R9 Below 1024 px the sidebar is a drawer. No page scrolls horizontally at any width.
- R10 Organisation signup (`/signup`) posts `POST /users/signup` with a `clinic_name`, which creates the tenant and makes the signer its Practice Owner, then signs them in. Field rules mirror the API (`UserRegister`: password 8 to 128 characters, names and email at most 255).
- R11 Password recovery (`/recover-password`) posts `POST /password-recovery/{email}` and confirms in words that never say whether the address has an account.
- R12 Password reset (`/reset-password?token=`) is where the emailed link lands (`{FRONTEND_HOST}/reset-password?token=...`, `backend/app/utils.py`). It posts `POST /reset-password/`; an invalid or expired token offers a new link. The token is sent only in the request body.
- R13 A signed-in visitor to sign in, signup or recovery goes to the app instead.
- R14 Administration (`/admin`) has three tabs. **Roles and permissions** shows every role against the full permission catalogue read from `GET /permissions` (21 codes today), with advisory grantability. **User access** lists an account's roles and effective permissions and grants or revokes a role behind a confirmation; `LAST_ADMINISTRATOR` and `GRANT_EXCEEDS_ACTOR` refusals are shown in the API's terms. **Accounts** (list, add, edit, deactivate) is offered only to the platform superuser, because the accounts API is superuser-only.
- R15 The Administration nav entry is shown only when `GET /users/me/permissions` includes `users:manage`; when that answer is unknown the entry is shown and the server's `403` is the refusal. A `429` on the administrative budget (20/min) is waited out and retried, never shown as a failure on the first refusal.
- R16 Settings (`/settings`) lets any signed-in person update their own name and email (`PATCH /users/me`), change their password (`PATCH /users/me/password`, current password required), and deactivate their own account (`DELETE /users/me`) behind a confirmation that then signs them out. The sidebar reads the same account, so a saved name shows there without a reload.

## Non-functional

- Sign-in page interactive within 1 s on a mid-range laptop.
- Initial JS at most 200 KB gzipped (measured about 151 KB).

## Out of scope (this phase)

- MFA, refresh tokens and SSO (blocked on D-003).
