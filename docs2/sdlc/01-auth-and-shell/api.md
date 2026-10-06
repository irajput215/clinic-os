# Auth and app shell: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `POST` | `/api/v1/login/access-token` | `backend/app/api/routes/login.py` | Form `username`, `password`. `200` gives `{access_token}`. `400` for bad credentials. Rate limited 20/min. |
| `GET` | `/api/v1/users/me` | `backend/app/api/routes/users.py` | Current user. `401` if the session is unusable. |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/users/me/permissions` | Today `GET /users/{id}/permissions` needs `users:manage`, so a clinician can't read their own permissions. Without this the UI can't hide controls by role and relies on `403`s. Response: `{permissions: string[]}`. |
