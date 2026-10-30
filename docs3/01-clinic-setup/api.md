# Clinic setup: API

Status: **Proposed.** Both routes live in `backend/app/modules/identity_tenancy/router.py` under the
existing `/tenants` prefix. Tenant is resolved from the session, never supplied.

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/v1/tenants/current/setup` | `tenant:configure` | `{steps: SetupStep[], required_done, required_total, ready}`. `403` for anyone else (the frontend hides the card). Rate limited 300/min |
| `GET` | `/api/v1/tenants/current/settings` | `tenant:read` | `TenantSettingsRead`; defaults when no row exists |
| `PATCH` | `/api/v1/tenants/current/settings` | `tenant:configure` | `TenantSettingsUpdate`, unknown fields rejected. Audited `tenant.settings_updated`. Administrative rate class (20/min) |

## Shapes

```ts
type SetupStep = {
  key: "clinic_name" | "hours" | "permissions_reviewed" | "team_invited"
     | "prescriber_ready" | "workflow" | "consents" | "booking_page" | "integrations"
  status: "done" | "todo" | "optional" | "informational"
  required: boolean
  href: string            // an app route, never an external URL
}

type TenantSettingsRead = {
  draft_staging_roles: ("NURSE" | "DOCTOR" | "ADMINISTRATOR")[]   // NURSE always included; ADMINISTRATOR is the code's reception/practice role
  adult_retention_years: number                                   // >= 7
  updated_at: string | null
}
```

## Errors

| Status | Code | When |
|---|---|---|
| `403` | `AUTHZ_DENIED` | Missing permission |
| `422` | `RETENTION_BELOW_MINIMUM` | `adult_retention_years < 7` |
| `422` | `STAGING_ROLES_INVALID` | Empty list, unknown role, or `NURSE` removed |

All errors use the existing `application/problem+json` envelope (`app/core/errors.py`).
