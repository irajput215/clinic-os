# Clinic setup: API

Status: **Built** (2026-10-31), with the differences under "As built". The routes live under the
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


## As built (2026-10-31)

- **Module:** `backend/app/modules/practice/` (owns `tenant_settings` and the setup read), so the
  checklist can ask the onboarding facade without an import cycle through `identity_tenancy`.
- **Schemas** are `PracticeSettingsRead` / `PracticeSettingsUpdate` (another `TenantSettingsUpdate`
  already exists). Both fields are sent together. Bad values are the standard body-validation `422`
  (minimum 7 years; `NURSE` always included; only `NURSE`, `DOCTOR`, `ADMINISTRATOR`).
- **Audit:** the existing `tenant.config_changed` with `changed_fields` (names only), not a new action.
- **Steps:** `consents` is always done (consent wording is versioned with the platform, feature 03 as
  built). `permissions_reviewed` is shown as optional and never ticked (no audit event for opening the
  grid yet). `prescriber_ready` uses feature 02's pack status.
- **Doctor-only prescribing (owner decision, 2026-10-31):** "who may stage drafts" (R4) is withdrawn.
  Only Doctors and Authorised Prescribers write scripts; the Nurse role lost `prescription:create` and
  `prescription:modify`, and the `draft_staging_roles` column was dropped. The settings hold retention
  only, which is stored, not enforced.
- **R7** ("Your clinic is ready" once) is not built: the card simply disappears when every required
  step is done.
