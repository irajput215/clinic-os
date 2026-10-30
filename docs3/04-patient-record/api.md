# Patient record: API

Status: **Proposed.** All under the existing `/patients` router; tenant from the session; `404` across
tenants; the care-relationship rule (D-007) applies to every patient-level route as it does today.

| Method | Path | Permission | Change |
|---|---|---|---|
| `POST` | `/api/v1/patients` | `patient:create` | `PatientCreate` gains `sex_at_birth` (required), `medicare_number`, `medicare_irn`, `ihi`, `receives_communications`, `timezone`. Status starts `CURRENT` |
| `PATCH` | `/api/v1/patients/{id}` | `patient:update` | Same new fields; `status` is **not** patchable here |
| `GET` | `/api/v1/patients/{id}` | `patient:read` | `PatientRead` gains `status`, `alerts[]`, `medicare_masked`, `ihi_masked`, `escript_ready: {ready, missing[]}`, `receives_communications`, `timezone`, `preferred_pharmacy` |
| `GET` | `/api/v1/patients?status=&cursor=` | `patient:read` | `status` filter (repeatable, closed list). Still no `q` in the URL |
| `POST` | `/api/v1/patients/search` | `patient:read` | Body may carry `{medicare}` or `{ihi}` for exact match via blind index |
| `POST` | `/api/v1/patients/{id}/status` | `patient:update` | `{status, reason, deceased_at?}`. `422 STATUS_REASON_REQUIRED` |
| `POST` | `/api/v1/patients/{id}/alerts` | `patient:update` | `{text, tone}` |
| `DELETE` | `/api/v1/patients/{id}/alerts/{alert_id}` | `patient:update` | Soft remove (`removed_at`) |
| `GET` / `POST` | `/api/v1/patients/{id}/emergency-contacts` | `patient:read` / `patient:update` | List / add |
| `DELETE` | `/api/v1/patients/{id}/emergency-contacts/{contact_id}` | `patient:update` | Soft remove |

## Refusals added elsewhere

| Route | Refusal |
|---|---|
| `POST /appointments`, `POST /public/{slug}/applications` | `422 PATIENT_BLOCKED` (public: the generic "can't book online, please call" wording — no status disclosed) |
| `POST /prescriptions` (stage) | `422 PATIENT_BLOCKED` |

## Errors

`422 IDENTIFIER_FORMAT` (`field: medicare | irn | ihi`, value never echoed) · `422 SEX_REQUIRED` ·
`422 STATUS_REASON_REQUIRED` · `422 TIMEZONE_INVALID`.

## Audit events

`patient.status_changed`, `patient.alert_added`, `patient.alert_removed`,
`patient.emergency_contact_added`, `patient.emergency_contact_removed`, `patient.identifier_updated`
(kind only, never the value).
