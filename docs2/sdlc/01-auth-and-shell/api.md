# Auth and app shell: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | `backend/app/api/routes/login.py` | Form `username`, `password`. `200` gives `{access_token}`. `400` for bad credentials. Rate limited 20/min. |
| `GET` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Current user. `401` if the session is unusable. |
| `POST` | `/api/v1/users/signup` | `backend/app/api/routes/users.py` | Organisation signup (`clinic_name`). Open registration only. |
| `POST` | `/api/v1/password-recovery/{email}` | `backend/app/api/routes/login.py` | Same answer for a known and an unknown address. Shares one 5/min window with reset. |
| `POST` | `/api/v1/reset-password/` | `backend/app/api/routes/login.py` | `{token, new_password}`. `400` for an invalid or expired token. |
| `PATCH` | `/api/v1/users/me`, `/api/v1/users/me/password` | `backend/app/api/routes/users.py` | Settings: own profile and password (current password required). |
| `DELETE` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Settings: deactivate own account. |
| `GET` | `/api/v1/roles`, `/api/v1/permissions` | `backend/app/modules/users_roles/router.py` | Administration matrix. `users:manage`; administrative budget 20/min. |
| `GET`, `POST`, `DELETE` | `/api/v1/users/{user_id}/roles[/{role_id}]`, `GET /api/v1/users/{user_id}/permissions` | `backend/app/modules/users_roles/router.py` | Administration access tab. `403 LAST_ADMINISTRATOR`, `403 GRANT_EXCEEDS_ACTOR`. |
| `GET` | `/api/v1/users/staff?skip=&limit=` | `backend/app/modules/users_roles/router.py` | Administration Staff tab. The caller's own organisation's accounts, `{data: [{id, email, full_name, is_active, created_at, roles: [{role_id, code, name}]}], count}`, ordered by name; `limit` 1 to 100 (default 50). `users:manage`; administrative budget 20/min. No audit event (no read action in the closed catalogue). |
| `POST` | `/api/v1/users/staff` | `backend/app/modules/users_roles/router.py` | Invite a staff member: `{email, full_name, role_ids[1..7]}`, no password. `201` `StaffMemberRead`. Creates the account in the session's organisation, grants the roles and emails `{FRONTEND_HOST}/accept-invite?token=...`. A body or query `tenant_id` is ignored and audited (`user.create` `DENIED` `CLIENT_TENANT_ID_IGNORED`); any other unknown key is `422`. `403 PERMISSION_NOT_HELD` / `GRANT_EXCEEDS_ACTOR`, `404` (a role absent or another organisation's), `409 EMAIL_UNAVAILABLE` (one answer whichever organisation holds the address), `503 EMAIL_NOT_CONFIGURED`. Audit: `user.create` plus one `user.permission_change` `GRANT` per role, same transaction. |
| `POST` | `/api/v1/users/invitations/accept` | `backend/app/modules/users_roles/router.py` | `{token, new_password}` (8 to 128). `200 {email}`, so the page signs the person in. `400 INVITATION_INVALID` for a tampered, expired (`STAFF_INVITATION_EXPIRE_HOURS`, default 72), already used or deactivated link: one answer. Own 5/min window. |
| `GET`, `POST`, `PATCH`, `DELETE` | `/api/v1/users/`, `/api/v1/users/{user_id}` | `backend/app/api/routes/users.py` | Administration accounts tab. Platform superuser only (frozen template layer). |
| `GET` | `/api/v1/users/me/permissions` | `backend/app/modules/users_roles/router.py` | The caller's own effective permission codes, sorted: `{permissions: string[]}`. Any authenticated, active account of an active organisation; not gated by `users:manage`. `401` unauthenticated or deactivated; `403` `NO_ORGANISATION` or `TENANT_NOT_ACTIVE`. No role is `200` with `[]`. Advisory only: every route still re-authorises. |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/users/me/permissions` | **Served** - agreed with the backend owner and moved to "Existing endpoints used" above. `GET /users/{id}/permissions` still needs `users:manage`; this is the self-service read a clinician uses so the UI can hide controls by role instead of relying on `403`s. |
