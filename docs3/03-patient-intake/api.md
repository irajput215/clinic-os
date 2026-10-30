# Patient intake: API

Status: **Proposed.** Public routes resolve the tenant from the clinic slug; staff routes from the
session. A `tenant_id` anywhere in a body is ignored and audited as a cross-tenant attempt (INV-1).

## Public (no sign-in)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/public/{clinic_slug}/application-form` | Current consent versions (id, kind, body), the condition list, partner pharmacies (name, suburb only). `404` for an unknown slug; `423 APPLICATIONS_CLOSED` when a required consent kind has no version (R20) |
| `POST` | `/api/v1/public/{clinic_slug}/applications` | Body: steps 1–6 + `{type, practitioner_id, starts_at}`. `201 {reference}` always the same shape (R10). `422` field errors; `422 UNDER_AGE`; `422 DECLARATION_MISMATCH`; `422 CONSENT_VERSION_STALE` if a newer version was published mid-form; `422 SLOT_NOT_OFFERED`. Rate limited 20/min per address. **Body never logged** |

The existing `POST /public/{clinic_slug}/bookings` is kept for one release for old clients, then removed.

## Staff

| Method | Path | Permission | Notes |
|---|---|---|---|
| `GET` | `/api/v1/intake-applications?status=SUBMITTED&cursor=` | `patient:read` | Keyset page of cards (no answers body) |
| `GET` | `/api/v1/intake-applications/{id}` | `patient:read` | Full application. Audited read |
| `POST` | `/api/v1/intake-applications/{id}/accept` | `patient:create` | `200` → patient id. `409 ALREADY_DECIDED` |
| `POST` | `/api/v1/intake-applications/{id}/reject` | `patient:create` | `{reason_code, note}`. `409 ALREADY_DECIDED` |
| `GET` | `/api/v1/patients/{patient_id}/intake-briefing` | `clinical_record:read` + care relationship | `404` when none; `403 AUTHZ_CARE_RELATIONSHIP_DENIED` per D-007. Audited |
| `GET` | `/api/v1/patients/{patient_id}/consents` | `patient:read` | Kind, version, method, signed date, `reconsent_needed` |
| `GET` | `/api/v1/consent-documents` | `tenant:read` | Kinds with current version |
| `POST` | `/api/v1/consent-documents/{kind}/versions` | `tenant:configure` | `{body, material_change}`; publishes the next version |
| `GET` / `POST` | `/api/v1/pharmacies` | `patient:read` / `patient:update` | Directory list (keyset) and add |
| `PATCH` | `/api/v1/patients/{patient_id}/pharmacy` | `patient:update` | Change preferred pharmacy (manual §3.5). Audited |

`404` across tenants everywhere.

## Reject reasons (closed list)

`NOT_ELIGIBLE`, `NEEDS_IN_PERSON_REVIEW`, `DUPLICATE`, `INCOMPLETE`, `OTHER`. The patient email never
names the reason.

## Audit events (register first)

`intake.application_submitted`, `intake.application_read`, `intake.application_accepted`,
`intake.application_rejected`, `intake.briefing_read`, `consent.version_published`, `consent.recorded`,
`pharmacy.created`, `patient.pharmacy_changed`. Payloads carry ids, codes and versions — never answers.
