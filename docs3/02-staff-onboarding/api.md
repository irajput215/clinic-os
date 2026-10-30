# Staff onboarding: API

Status: **Proposed.** Tenant resolved from the session. Every write audited in the same transaction.

## Onboarding and the vault (`users_roles`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/v1/users/staff` | `users:manage` | **Changed:** each row gains `onboarding_status` (`INVITED`, `ACTIVE`, `PACK_INCOMPLETE`, `READY`) |
| `GET` | `/api/v1/users/{user_id}/onboarding` | self, or `tenant:configure` / `audit:read` | `{pack_complete, agreement, identifiers[], sops[], missing[]}`. Identifier values masked. Audited read |
| `PUT` | `/api/v1/users/{user_id}/identifiers/{kind}` | `tenant:configure` + step-up token | Body `{value, expires_on?, location_clinic_id?, status, verification_method}`. Records `verified_by`/`verified_at` from the session. `422 IDENTIFIER_FORMAT` names the expected format |
| `POST` | `/api/v1/users/{user_id}/agreements` | `tenant:configure` | `{agreement_version, signed_on}`; attestation from the session |
| `GET` | `/api/v1/users/me/first-hour` | signed in | The role cards for the caller, lines filtered to built screens |

`404` for a user in another tenant (never `403`). A step-up token is single-use and bound to
`operation=identifier.update` and the target user.

## SOPs (new module `sops`)

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/v1/sops` | signed in | SOPs that apply to the caller (all, for `tenant:configure`), with `my_acknowledged_version` |
| `GET` | `/api/v1/sops/{sop_id}` | signed in, SOP applies to caller | Current version body + version list |
| `POST` | `/api/v1/sops` | `tenant:configure` | Creates SOP + version 1 |
| `POST` | `/api/v1/sops/{sop_id}/versions` | `tenant:configure` | Publishes the next version; resets acknowledgement |
| `POST` | `/api/v1/sops/{sop_id}/versions/{version}/acknowledge` | signed in, SOP applies | `409 NOT_CURRENT_VERSION` for an old version; idempotent |
| `GET` | `/api/v1/sops/matrix` | `tenant:configure` or `audit:read` | Staff × SOP × acknowledged version |

## Changed: signing

| Method | Path | Change |
|---|---|---|
| `POST` | `/api/v1/prescriptions/{id}/sign` | New refusal **before** the safety gate: `403 PRESCRIBER_NOT_READY` with `missing: ["AGREEMENT", "AHPRA", "PRESCRIBER_NUMBER", "SOP:<id>"]`. Audited as `prescription.sign` `DENIED` |

## Audit events (register in `audit/actions.py` first)

`practitioner.identifier_updated`, `practitioner.agreement_recorded`, `practitioner.onboarding_read`,
`sop.published`, `sop.acknowledged`, `prescription.sign` (reason `PRESCRIBER_NOT_READY`).
Payloads carry kinds and statuses, never identifier values.
