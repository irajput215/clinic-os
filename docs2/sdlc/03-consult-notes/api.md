# Consult notes: API

## Existing endpoints used

| Method | Path | Source | Notes |
|---|---|---|---|
| `GET` | `/api/v1/patients/{patient_id}/clinical-records` | `backend/app/modules/clinical_records/router.py` (#47) | Keyset page of `ClinicalRecordSummary` |
| `POST` | `/api/v1/clinical-records` | same | `{patient_id, record_type: 'NOTE', soap}` |
| `POST` | `/api/v1/clinical-records/{id}/sign` | same | Author only; immutable afterwards |
| `POST` | `/api/v1/clinical-records/{id}/amendments` | same | `{soap, amendment_reason}` |

No new endpoints needed.

## How the app reads them (proven against the module)

- The list is paged with `limit` (max 100) and `cursor`; the app follows `next_cursor` until it is null.
- `soap` is rendered by the server into one Markdown narrative (`## Subjective\n\n...`, `body_format: MARKDOWN`); the app parses those headings back for display.
- The server renders every section it is sent, including an empty string, so the app sends only the sections that were written.
- Signing sets the record's `signed_at`; an amendment is a new, unsigned version on a signed record. The UI shows such a record as Signed with `Amended · vN`.
- Refusals are RFC 7807 with `detail.code`: `NOTE_ALREADY_SIGNED` (403), `SIGN_NOT_VERSION_AUTHOR` (403), `AMENDMENT_REASON_REQUIRED` (422), `VERSION_CONFLICT` (409).
