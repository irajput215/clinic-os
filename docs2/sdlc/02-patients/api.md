# Patients: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients?limit=1..25` | `backend/app/modules/patients/router.py` | `{data: PatientRead[], count}` |
| `POST` | `/api/v1/patients` | same | `PatientCreate`; `201` gives `PatientRead` |
| `GET` | `/api/v1/patients/{patient_id}` | same | `404` when absent or another tenant's |
| `PATCH` | `/api/v1/patients/{patient_id}` | same | `PatientUpdate`, unknown fields rejected |

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/patients?q=&cursor=` | Server-side name/DOB search with keyset paging. Until then the UI can only reach the first 25 patients. |
