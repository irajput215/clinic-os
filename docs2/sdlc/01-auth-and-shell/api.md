# Auth and app shell: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | `backend/app/api/routes/login.py` | Form `username`, `password`. `200` gives `{access_token}`. `400` for bad credentials. Rate limited 20/min. |
| `GET` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Current user. `401` if the session is unusable. |
| `POST` | `/api/v1/users/signup` | `backend/app/modules/users_roles/router.py` | Organisation signup, verified by email ([D-008](../../../docs/reference/decisions/D-008-signup-email-verification.md)). Body `{email, password, full_name, clinic_name}` (unknown keys `422`). `202 {request_id, expires_in_hours}` for **every** address: a new one is emailed a single-use link to `{FRONTEND_HOST}/verify-email?token=...`, one that already has an account is emailed a notice to sign in or reset the password instead; status, body and work are the same. Nothing is created until the link is used. `403` without open registration, `503 EMAIL_NOT_CONFIGURED` without outgoing mail (nothing written). 20/min per client address. |
| `POST` | `/api/v1/users/signup/resend` | `backend/app/modules/users_roles/router.py` | `{request_id}`. `202` always; emails that request's message again with a fresh link (the previous link is then refused) and restarts the window; nothing for an unknown, expired or verified request, or after 5 emails. 20/min per client address (own window). |
| `POST` | `/api/v1/users/signup/verify` | `backend/app/modules/users_roles/router.py` | `{token}`. Creates the organisation, the account and its Practice Owner grant in one transaction, audits `user.create`, and answers `200 {access_token, token_type}`: the person is signed in. `400 SIGNUP_LINK_INVALID` for a tampered, expired, replaced or used link, or an address that has an account by now: one answer. 20/min per client address (own window). |
| `POST` | `/api/v1/password-recovery/{email}` | `backend/app/api/routes/login.py` | Same answer for a known and an unknown address. Shares one 5/min window with reset. |
| `POST` | `/api/v1/reset-password/` | `backend/app/api/routes/login.py` | `{token, new_password}`. `400` for an invalid or expired token. |
| `PATCH` | `/api/v1/users/me`, `/api/v1/users/me/password` | `backend/app/api/routes/users.py` | Settings: own profile and password (current password required). |
| `DELETE` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Settings: deactivate own account. |
| `GET` | `/api/v1/roles`, `/api/v1/permissions` | `backend/app/modules/users_roles/router.py` | Administration matrix. `users:manage`; administrative budget 20/min. |
| `GET`, `POST`, `DELETE` | `/api/v1/users/{user_id}/roles[/{role_id}]`, `GET /api/v1/users/{user_id}/permissions` | `backend/app/modules/users_roles/router.py` | Administration access tab. `403 LAST_ADMINISTRATOR`, `403 GRANT_EXCEEDS_ACTOR`. |
| `GET` | `/api/v1/users/staff?skip=&limit=` | `backend/app/modules/users_roles/router.py` | Administration Staff tab. The caller's own organisation's accounts, `{data: [{id, email, full_name, is_active, status, invitation, created_at, roles: [{role_id, code, name}]}], count}`, ordered by name; `limit` 1 to 100 (default 50). `status` is `INVITED` (an invitation is outstanding: the person has not yet chosen a password), `ACTIVE` or `INACTIVE` (deactivated). `invitation` is `{sent_at, expires_at, expired}` while the status is `INVITED`, otherwise `null`; `expired` is decided by the server clock. `users:manage`; administrative budget 20/min. No audit event (no read action in the closed catalogue). |
| `POST` | `/api/v1/users/staff` | `backend/app/modules/users_roles/router.py` | Invite a staff member: `{email, full_name, role_ids[1..7]}`, no password. `201` `StaffMemberRead`. Creates the account in the session's organisation, grants the roles and emails `{FRONTEND_HOST}/accept-invite?token=...`. A body or query `tenant_id` is ignored and audited (`user.create` `DENIED` `CLIENT_TENANT_ID_IGNORED`); any other unknown key is `422`. `403 PERMISSION_NOT_HELD` / `GRANT_EXCEEDS_ACTOR`, `404` (a role absent or another organisation's), `409 EMAIL_UNAVAILABLE` (one answer whichever organisation holds the address), `503 EMAIL_NOT_CONFIGURED`. Audit: `user.create` plus one `user.permission_change` `GRANT` per role, same transaction. |
| `POST` | `/api/v1/users/staff/{user_id}/invitation` | `backend/app/modules/users_roles/router.py` | **Resend invite.** No body. Issues a fresh link to the person's address and retires the previous one (it is refused like a used link), and resets the expiry to `STAFF_INVITATION_EXPIRE_HOURS` from now. `200` `StaffMemberRead` with the new `invitation`. Permission exactly as for sending one: `users:manage` (refusal `403 PERMISSION_NOT_HELD`, audited) and R3 over the union of the bundles of the roles the person holds now (`403 GRANT_EXCEEDS_ACTOR`, audited). `404` for an account that is absent or another organisation's (checked before R3, so it leaks nothing). `409 INVITATION_NOT_PENDING` when the person already accepted (or set a password any other way), was never invited (the organisation's founder) or is deactivated; audited. `503 EMAIL_NOT_CONFIGURED` without outgoing mail; nothing changes. The email is the invitation email again, nothing more (name, organisation, address, validity, link). Audit: `user.create` `SUCCESS` with `change = INVITATION_RESENT`, same transaction as the new link; administrative budget 20/min (the invitation's own class). |
| `POST` | `/api/v1/users/invitations/accept` | `backend/app/modules/users_roles/router.py` | `{token, new_password}` (8 to 128). `200 {email}`, so the page signs the person in. `400 INVITATION_INVALID` for a tampered, expired (`STAFF_INVITATION_EXPIRE_HOURS`, default 72), already used or deactivated link: one answer. Own 5/min window. |
| `GET`, `POST`, `PATCH`, `DELETE` | `/api/v1/users/`, `/api/v1/users/{user_id}` | `backend/app/api/routes/users.py` | Administration accounts tab. Platform superuser only (frozen template layer). |
| `GET` | `/api/v1/users/me/permissions` | `backend/app/modules/users_roles/router.py` | The caller's own effective permission codes, sorted: `{permissions: string[]}`. Any authenticated, active account of an active organisation; not gated by `users:manage`. `401` unauthenticated or deactivated; `403` `NO_ORGANISATION` or `TENANT_NOT_ACTIVE`. No role is `200` with `[]`. Advisory only: every route still re-authorises. |

## Clinic display name

**Status: built 2026-10-08 (Milestone 4).** `backend/app/modules/identity_tenancy/` (the tenancy
module owns `tenants`) and the public read in `backend/app/modules/appointments/router.py`.

The sidebar and the public booking page used to show a name derived from the routing slug, because
the only name a tenant had was `legal_name`, which is CONFIDENTIAL
(`docs/features/01-tenancy-and-clinics/03-design.md`) and must never be shown publicly. A tenant now
has a second, **PUBLIC** name, `display_name` (the classification ladder of
`docs/features/01-tenancy-and-clinics/05-data-and-audit.md`: "approved for release to anyone").

| Method | Path | Auth / permission | Contract |
|---|---|---|---|
| `GET` | `/api/v1/tenants/current/profile` | any member of an active organisation; no permission code | `{display_name}` of the session's own organisation. `401` no session; `403 NO_ORGANISATION` / `TENANT_NOT_ACTIVE`. Read class (300/min). No audit event (PUBLIC data, and the closed catalogue names no tenant read). |
| `PATCH` | `/api/v1/tenants/current/profile` | `tenant:configure` (Practice Owner only); **no step-up** | Body `{display_name}`, strict (`422` on any unknown key) except that a `tenant_id` is ignored and audited `DENIED` `CLIENT_TENANT_ID_IGNORED`. The name is normalised (whitespace runs collapsed, ends trimmed) and must then be 1 to 120 characters with no control or format character (`422` otherwise). `200 {display_name}`. `403 PERMISSION_NOT_HELD`, audited. Administrative class (20/min). |
| `GET` | `/api/v1/public/{clinic_slug}` | none (public) | `{display_name}` only, never `legal_name`, the tenant id or the status. Unknown, malformed or non-`ACTIVE` clinic: the same `404 CLINIC_NOT_FOUND` as the other public routes. Rate-limited with the public slots (60/min per address). |

Decisions recorded with it:

- **Permission: `tenant:configure`, no new code.** `docs/features/01-tenancy-and-clinics/03-design.md`
  gives tenant configuration to `tenant:configure`, which only the Practice Owner holds; feature 15's
  `admin:*` codes are candidates, not granted (15 OPEN-3). The permission matrix is unchanged.
- **No step-up.** R12's step-up guards a *security* setting (`PATCH /tenants/current`, which still
  refuses every caller `403 STEP_UP_REQUIRED`). The display name changes how the clinic is labelled
  and nothing about who may do what, so it is its own sub-resource rather than a field of that route.
  The event records `step_up: false`.
- **Reading needs no permission.** The name is PUBLIC (the booking page shows it to anyone), so every
  member of the organisation sees it in the sidebar, not only `tenant:read` holders. The slug, which
  builds the booking link, is still `tenant:read`.
- **Audit:** `tenant.config_changed`, resource type `TENANT`, resource id the tenant, payload
  `changed_fields: ["display_name"]` and `step_up: false`: field names only, never the name. Registered
  in the closed catalogue on 2026-10-08 (`docs/features/04-audit-log/05-data-and-audit.md`). A refusal
  is written on its own transaction before the `403`; a change is written on the change's
  transaction, so a failed audit write rolls the rename back (INV-4). Saving the name the clinic
  already has writes nothing and records nothing.
- **Backfill: the slug, never `legal_name`.** Existing tenants got the name their booking page already
  showed (`green-valley-clinic` -> `Green Valley Clinic`): `legal_name` is CONFIDENTIAL even where it
  holds the name typed at signup, and copying it into a PUBLIC column would declassify it without a
  decision. New clinics start with the clinic name typed at signup, normalised; a signup name longer
  than 120 characters is cut at the last whole word (signup itself still accepts 255, the legal name's
  bound).
- **Grants:** `clinos_app` gains `SELECT (display_name)` and `UPDATE (display_name, updated_at)` on
  `tenants`, its only `UPDATE` there (`tests/security/test_tenant_grants.py`).
- **Emails:** the staff invitation names the clinic by its display name (`tenant_display_name`), never
  the legal name.

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/users/me/permissions` | **Served** - agreed with the backend owner and moved to "Existing endpoints used" above. `GET /users/{id}/permissions` still needs `users:manage`; this is the self-service read a clinician uses so the UI can hide controls by role instead of relying on `403`s. |
