# Auth and app shell: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | `backend/app/api/routes/login.py` | Form `username`, `password`. `200` gives `{access_token}`. `400` for bad credentials. Rate limited 20/min. |
| `GET` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Current user. `401` if the session is unusable. |
| `GET` | `/api/v1/users/me/permissions` | `backend/app/modules/users_roles/router.py` | The caller's own effective permission codes, sorted: `{permissions: string[]}`. Any authenticated, active account of an active organisation; not gated by `users:manage`. `401` unauthenticated or deactivated; `403` `NO_ORGANISATION` or `TENANT_NOT_ACTIVE`. No role is `200` with `[]`. Advisory only: every route still re-authorises. |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/users/me/permissions` | **Served** - agreed with the backend owner and moved to "Existing endpoints used" above. `GET /users/{id}/permissions` still needs `users:manage`; this is the self-service read a clinician uses so the UI can hide controls by role instead of relying on `403`s. |
