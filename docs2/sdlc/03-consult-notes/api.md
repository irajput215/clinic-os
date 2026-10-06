# Consult notes: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients/{patient_id}/clinical-records` | `feat/clinical-records`: `modules/clinical_records/router.py` | Keyset page of `ClinicalRecordSummary` |
| `POST` | `/api/v1/clinical-records` | same | `{patient_id, record_type: 'NOTE', soap}` |
| `POST` | `/api/v1/clinical-records/{id}/sign` | same | Author only; immutable afterwards |
| `POST` | `/api/v1/clinical-records/{id}/amendments` | same | `{soap, amendment_reason}` |

No new endpoints needed.
