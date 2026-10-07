# Auth and app shell: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | `backend/app/api/routes/login.py` | Form `username`, `password`. `200` gives `{access_token}`. `400` for bad credentials. Rate limited 20/min. |
| `GET` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Current user. `401` if the session is unusable. |
| `POST` | `/api/v1/users/signup` | `backend/app/api/routes/users.py` | Organisation signup (`clinic_name`). Open registration only. Rate limited 20/min. A taken email is `400` (it discloses that the address has an account: a recorded residual risk, see `register_user`). |
| `POST` | `/api/v1/password-recovery/{email}` | `backend/app/api/routes/login.py` | Same answer for a known and an unknown address. Shares one 5/min window with reset. |
| `POST` | `/api/v1/reset-password/` | `backend/app/api/routes/login.py` | `{token, new_password}`. `400` for an invalid or expired token. |
| `PATCH` | `/api/v1/users/me`, `/api/v1/users/me/password` | `backend/app/api/routes/users.py` | Settings: own profile and password (current password required). |
| `DELETE` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Settings: deactivate own account. |
| `GET` | `/api/v1/roles`, `/api/v1/permissions` | `backend/app/modules/users_roles/router.py` | Administration matrix. `users:manage`; administrative budget 20/min. |
| `GET`, `POST`, `DELETE` | `/api/v1/users/{user_id}/roles[/{role_id}]`, `GET /api/v1/users/{user_id}/permissions` | `backend/app/modules/users_roles/router.py` | Administration access tab. `403 LAST_ADMINISTRATOR`, `403 GRANT_EXCEEDS_ACTOR`. |
| `GET`, `POST`, `PATCH`, `DELETE` | `/api/v1/users/`, `/api/v1/users/{user_id}` | `backend/app/api/routes/users.py` | Administration accounts tab. Platform superuser only (frozen template layer). |
| `GET` | `/api/v1/users/me/permissions` | `backend/app/modules/users_roles/router.py` | The caller's own effective permission codes, sorted: `{permissions: string[]}`. Any authenticated, active account of an active organisation; not gated by `users:manage`. `401` unauthenticated or deactivated; `403` `NO_ORGANISATION` or `TENANT_NOT_ACTIVE`. No role is `200` with `[]`. Advisory only: every route still re-authorises. |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/users/me/permissions` | **Served** - agreed with the backend owner and moved to "Existing endpoints used" above. `GET /users/{id}/permissions` still needs `users:manage`; this is the self-service read a clinician uses so the UI can hide controls by role instead of relying on `403`s. |
