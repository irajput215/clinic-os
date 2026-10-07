# TGA approvals: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients/{patient_id}/tga-approvals` | `backend/app/modules/tga_approvals/router.py` (#46) | `TgaApprovalsPublic` |
| `POST` | `/api/v1/tga-approvals` | same | `TgaApprovalCreate`, `extra=forbid`, two-year and forward-window checks |
| `POST` | `/api/v1/tga-approvals/{id}/verify` | same | `{tga_application_number}`, four-eyes |
| `POST` | `/api/v1/tga-approvals/{id}/revoke` | same | `{reason_code}` |
| `POST` | `/api/v1/tga-approvals/match` | same | The gate lookup. Not called by the app yet: feature 07 is preview, and its server will run the gate itself |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/tga-approvals?state=&expiring_within_days=&cursor=` | A tenant-wide register for the practice. Today only the per-patient list exists (`GET /tga-approvals` answers 405), so until this lands the register screen shows a designed refusal naming this endpoint, not preview data. Response `TgaApprovalsPublic` plus `patient_display_name` (or the UI joins on patients). |
