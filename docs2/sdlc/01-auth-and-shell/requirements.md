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

## Non-functional

- Sign-in page interactive within 1 s on a mid-range laptop.
- Initial JS at most 200 KB gzipped (measured about 151 KB).

## Out of scope (this phase)

- MFA, refresh tokens and SSO (blocked on D-003).
- Password recovery screens (exist in `frontend/`; to be ported).
