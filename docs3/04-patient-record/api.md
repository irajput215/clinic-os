# Patient record: API

Status: **Built** (docs3 feature 04). All under the existing `/patients` router; tenant from the session; `404` across
tenants; the care-relationship rule (D-007) applies to every patient-level route as it does today.

| Method | Path | Permission | Change |
|---|---|---|---|
| `POST` | `/api/v1/patients` | `patient:create` | `PatientCreate` gains `medicare_number`, `medicare_irn`, `ihi`, `receives_communications`, `timezone`. Status starts `CURRENT`. `sex_at_birth` stays optional in the API (the form marks it "needed for eScripts"; `escript_ready` names it when missing) |
| `PATCH` | `/api/v1/patients/{id}` | `patient:update` | Same new fields; `status` is **not** patchable here |
| `GET` | `/api/v1/patients/{id}` | `patient:read` | `PatientRead` gains `status`, `status_reason`, `medicare_masked`, `medicare_irn`, `ihi_masked`, `escript_ready: {ready, missing[]}`, `receives_communications`, `timezone`. Alerts are their own route; `preferred_pharmacy` arrives with feature 03 |
| `GET` | `/api/v1/patients?status=&cursor=` | `patient:read` | `status` filter (repeatable, closed list). Still no `q` in the URL |
| `POST` | `/api/v1/patients/search` | `patient:read` | A 10-digit word in `q` matches a Medicare number, and `800360…` (16 digits) an IHI, exactly, through the blind index |
| `POST` | `/api/v1/patients/{id}/status` | `patient:update` | `{status, reason, deceased_at?}`. `422 STATUS_REASON_REQUIRED` |
| `POST` | `/api/v1/patients/{id}/alerts` | `patient:update` | `{text, tone}` |
| `POST` | `/api/v1/patients/{id}/alerts/{alert_id}/remove` | `patient:update` | Soft remove (`removed_at`); nothing under `/patients` is a `DELETE` |
| `GET` / `POST` | `/api/v1/patients/{id}/emergency-contacts` | `patient:read` / `patient:update` | List / add |
| `POST` | `/api/v1/patients/{id}/emergency-contacts/{contact_id}/remove` | `patient:update` | Soft remove |

## Refusals added elsewhere

| Route | Refusal |
|---|---|
| `POST /appointments`, `POST /public/{slug}/applications` | `422 PATIENT_BLOCKED` (public: the generic "can't book online, please call" wording — no status disclosed) |
| `POST /prescriptions` (stage) | `422 PATIENT_BLOCKED` |

## Errors

As built: identifier, IRN and time-zone format errors are the standard body-validation `422`;
`422 STATUS_REASON_REQUIRED` (reason or date of death missing); `422 PATIENT_BLOCKED` elsewhere.

## Audit events

As built, every change is `patient.update` (already in the catalogue) with `changed_fields` naming
what changed (`status`, `alerts`, `emergency_contacts`, `medicare_number`, `ihi`) - never a value. A
status change carries `reason = STATUS_<NEW_STATUS>`; the free-text reason is never audited.
