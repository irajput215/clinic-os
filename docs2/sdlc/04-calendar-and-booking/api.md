# Calendar and booking: API

**Status: Agreed 2026-10-07 (owner).** Built in `backend/app/modules/appointments/`. The owner
approved the contract, its schema, and the two unauthenticated public routes.

All routes follow the repo's non-negotiables: tenant from the session only (public routes: from the
slug, server-side), RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807
errors with `detail.code`. A `tenant_id` in a body or query string is ignored and audited as
`appointment.create` `DENIED` `CLIENT_TENANT_ID_IGNORED`.

## Endpoints

| Method | Path | Auth / permission | Contract |
|---|---|---|---|
| `GET` | `/api/v1/practitioners` | `patient:read` | Bookable staff: **active** accounts holding `DOCTOR`, `AUTHORISED_PRESCRIBER` (booked as a doctor) or `NURSE`. `[{id, name, role: DOCTOR\|NURSE, title}]`; `title` is the role's display name. `PRACTICE_OWNER` alone is not bookable. |
| `GET` | `/api/v1/appointments?from=&to=&practitioner_id=` | `patient:read` | Appointments **starting** in `[from, to)` (timezone-aware instants, at most 31 days, else `422 INVALID_RANGE`), earliest first. `AppointmentRead[]`: `{id, patient_id, patient_name, practitioner_id, type, status, starts_at, ends_at, source: STAFF\|PUBLIC_BOOKING, created_at}`. |
| `POST` | `/api/v1/appointments` | `patient:update` | `{patient_id, practitioner_id, type, starts_at}` (strict; `starts_at` must carry an offset). The server computes `ends_at` from the type. `201 AppointmentRead`. `404 PATIENT_NOT_FOUND` / `404 PRACTITIONER_NOT_FOUND` (absent, another tenant's, or not bookable), `422 TYPE_NOT_OFFERED`, **`409 APPOINTMENT_OVERLAP`** from `EXCLUDE USING gist (tenant_id WITH =, practitioner_id WITH =, during WITH &&) WHERE (status NOT IN ('CANCELLED','NO_SHOW'))`, where `during = tstzrange(starts_at, ends_at, '[)')` is derived by trigger. The message names the practitioner and the clashing time, never the other patient. |
| `POST` | `/api/v1/appointments/{id}/status` | `patient:update` | `{status}`. `409 ILLEGAL_STATE_TRANSITION` outside R4 (the service refuses first; a trigger enforces the same table). `404 APPOINTMENT_NOT_FOUND`. Audited `appointment.state_change` `{from_state, to_state}`. |
| `GET` | `/api/v1/patients/{id}/appointments` | `patient:read` | **Added** for the patient record's Appointments tab and Overview card: one patient's bookings, newest first (max 200). `404 PATIENT_NOT_FOUND`. |
| `GET` | `/api/v1/public/{clinic_slug}/slots?type=` | none | Rate-limited 60/min per address. Tenant resolved from the slug **server-side**; an unknown, malformed or non-`ACTIVE` clinic is one uniform `404 CLINIC_NOT_FOUND`. `PublicSlot[]` `{practitioner_id, practitioner_name, starts_at, ends_at}` from tomorrow to 14 days out. `practitioner_name` never falls back to an email. |
| `POST` | `/api/v1/public/{clinic_slug}/bookings` | none | `application/json` only (`415` otherwise; CSRF-safe by construction). Rate-limited 10/min per address and 5/hour per email (keyed HMAC, never the address in clear). Body: `{type, practitioner_id, starts_at, given_name, family_name, date_of_birth, email, phone (AU mobile), consent: true}`, strict. `201 {reference}` (`BK-XXXXXX`), identical whether the patient was new or matched. `422 SLOT_NOT_OFFERED` (not a slot the clinic offers), `422 BOOKING_AGE_NOT_MET` (under 18 in Sydney), **`409 SLOT_TAKEN`**. |

## Decisions recorded with the agreement

- **Permissions: no new code.** Reading the calendar is `patient:read`; booking and moving a booking is
  `patient:update` (`users_roles/catalog.py` `APPOINTMENT_PERMISSIONS`). That covers reception
  (`ADMINISTRATOR`) and every clinical role; `PHARMACY` and `COMPLIANCE_AUDITOR` read but cannot book.
- **Availability is tenant configuration.** No document fixes working hours or slot length, and
  availability editing is out of scope (requirements). Table `appointment_settings` (optional row per
  tenant: `opens_at`, `closes_at`, `working_days` ISO 1-7). Without a row: **09:00-17:00, Monday to
  Friday**. Public slots step by the type's length (15 or 30 minutes, R2) from opening, the last ending
  at or before closing, from tomorrow (no same-day online booking) for 14 days. All computed in
  `Australia/Sydney` on the database clock (R7). No route writes the table yet; the application role
  may only read it.
- **Minimal PHI on the public route.** The eligibility questions (what help, tried standard
  treatment) stay in the browser and are not sent. The patient is created or matched on **all of**
  given name, family name, date of birth and email (case-insensitive); a matched record is never
  changed. The new record is audited `patient.create` (no actor, `actor_role = PUBLIC_BOOKING`,
  `source_ip`), on the same transaction as the booking, so a refused booking leaves no patient behind.
- **R3 vs INV-5.** R3 asks the refusal to name the clash; `docs/` forbids PHI in errors, so it names the
  practitioner and the time (`Dr X is already booked from 09:00 to 09:15.`), not the other patient.
- **R6.** A public booking is `source = PUBLIC_BOOKING` and appears on the calendar marked "Public
  booking page"; it links to the real patient record it created or matched.
- **Clinic identity on the public page** is derived from the slug (the only public identity a clinic
  has: `tenants.legal_name` is CONFIDENTIAL in `01-tenancy-and-clinics/03-design.md`). The slug stays
  routing only, never an authorisation input: it selects which clinic's free slots are read.
- **`docs/features/05-patients/01-requirements.md`** lists "appointments, booking and intake" as out of
  scope for the patients MVP; this feature owns them in their own module and touches `patients` only
  through its service facade.
- **Audit catalogue** (`docs/features/04-audit-log/05-data-and-audit.md`): resource type `APPOINTMENT`,
  actions `appointment.create` (`patient_id`, `source`) and `appointment.state_change`
  (`from_state`, `to_state`). Reads are not audited, deferred with `patient.read` (T1-34).
- **Deferred:** CAPTCHA (a new third-party data flow, needs its own decision); confirmations by SMS or
  email (out of scope in requirements); rate limits are in-process (`app/core/rate_limit.py` notes).
