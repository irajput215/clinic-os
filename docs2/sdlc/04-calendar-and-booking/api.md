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
| `GET` | `/api/v1/public/{clinic_slug}` | none | **Added 2026-10-08.** The clinic's PUBLIC display name for the page heading: `{display_name}` only. Same uniform `404 CLINIC_NOT_FOUND`; rate-limited with the slots. Contract: [`01-auth-and-shell/api.md`](../01-auth-and-shell/api.md), "Clinic display name". |
| `GET` | `/api/v1/public/{clinic_slug}/slots?type=` | none | Rate-limited 60/min per address. Tenant resolved from the slug **server-side**; an unknown, malformed or non-`ACTIVE` clinic is one uniform `404 CLINIC_NOT_FOUND`. `PublicSlot[]` `{practitioner_id, practitioner_name, starts_at, ends_at}` from tomorrow to 14 days out. `practitioner_name` never falls back to an email. |
| `POST` | `/api/v1/public/{clinic_slug}/bookings` | none | `application/json` only (`415` otherwise; CSRF-safe by construction). Rate-limited 10/min per address and 5/hour per email (keyed HMAC, never the address in clear). Body: `{type, practitioner_id, starts_at, given_name, family_name, date_of_birth, email, phone (AU mobile), consent: true}`, strict. `201 {reference}` (`BK-XXXXXX`), identical whether the patient was new or matched. `422 SLOT_NOT_OFFERED` (not a slot the clinic offers), `422 BOOKING_AGE_NOT_MET` (under 18 in Sydney), **`409 SLOT_TAKEN`**. |

## Clinic hours, slot length and booking emails (Milestone 4, 2026-10-08)

**Status: built 2026-10-08.** `backend/app/modules/appointments/` (`models.py`, `service.py`,
`notifications.py`, `router.py`). Scheduling decision: [D-007](../../../docs/reference/decisions/D-007-scheduled-jobs-and-booking-reminders.md).

| Method | Path | Auth / permission | Contract |
|---|---|---|---|
| `GET` | `/api/v1/appointment-settings` | any member of an active organisation; no permission code | `{slot_minutes, hours: [{weekday 1-7, opens_at "HH:MM" \| null, closes_at "HH:MM" \| null}] (always 7, Monday first), is_default}`. Opening hours are PUBLIC (`01-tenancy-and-clinics/05-data-and-audit.md` names "public clinic address and opening hours" as its PUBLIC example), and the calendar of every role reads them. Read class (300/min). |
| `PUT` | `/api/v1/appointment-settings` | `tenant:configure` (Practice Owner); no step-up | Body `{slot_minutes, hours: [7 rows]}`, strict (a `tenant_id` is ignored and audited `CLIENT_TENANT_ID_IGNORED`). Rules, each a `422` naming the day: one row per weekday 1-7, no duplicate; a day is open (both times) or closed (both `null`); `opens_at < closes_at`; times on 5-minute marks; the open span is at least one slot long; at least one open day; `slot_minutes` in `{10, 15, 20, 30, 60}`. One interval per day, so two openings of one day cannot overlap by construction. `200` with the saved settings and `bookings_outside_hours`: how many upcoming live bookings now fall outside the hours (they are kept, never cancelled). `403 PERMISSION_NOT_HELD`, audited. Administrative class (20/min). |
| `POST` | `/api/v1/internal/booking-notifications/run` | bearer `BOOKING_NOTIFICATIONS_RUN_TOKEN` (no session); `404` when the token is not configured | Sends every due confirmation and reminder, one tenant per transaction. `{sent, skipped, failed, retried}` counts only. `401` on a wrong token. `503 EMAIL_NOT_CONFIGURED` when outgoing mail is off. 20/min. |

**Slots.** The public page offers, for each open day from tomorrow to 14 days out, a start every
`slot_minutes` from opening, each ending (start + the visit type's length, R2) at or before closing.
Without a settings row the clinic is open Monday to Friday 09:00-17:00 with 15-minute slots. (Until
2026-10-08 starts stepped by the visit type's length, so a 30-minute consult was offered every 30
minutes; it is now offered on the clinic's slot grid.) Staff bookings are not limited to the hours:
reception may book outside them. The calendar's day view spans the day's hours (08:00-18:00 when the
day is closed), extended to any booking outside them, with one clickable slot per `slot_minutes`.

**Booking emails.** Sent to the patient's email address on file (a public booking always has one; a
staff-created patient may not, and is then skipped), only while outgoing email is configured
(`settings.emails_enabled`):

- a **confirmation** when a booking is made, from the public page or by staff, sent right after the
  booking commits;
- a **reminder** 24 hours before the start (none when the booking is made less than 24 hours ahead).

The email content contract. The docs are silent on booking email content, so each email carries the
minimum and nothing clinical: the clinic's **display name** (PUBLIC), the **date and time** in Sydney
time, the **booking reference** (`BK-XXXXXX`) and **how to change it** ("contact the clinic and quote
your reference"). Never the patient's name, date of birth or phone, the visit type, the practitioner,
the reason for the visit, or any link that signs anyone in. The subject carries the clinic name only.
Every value is HTML-escaped. Each send is audited `integration.request` (`provider: SMTP`,
`outcome_class`), resource the notification; no address, name or time is in the trail or the logs.

**Audit.** A settings change is `tenant.config_changed` with `changed_fields` (`slot_minutes`,
`hours`) and `step_up: false`, on the change's transaction; a refusal is audited `DENIED` before the
`403`.

**Schema.** `appointment_settings` loses `opens_at`, `closes_at` and `working_days` and gains
`slot_minutes`; `appointment_hours` holds seven rows per configured clinic (closed = both times
`null`), so closing a day is an `UPDATE` and the application role needs no `DELETE`;
`appointment_notifications` is the outbox. All three are tenant tables with forced RLS. The migration
copies each existing row's hours onto its working days.

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
- **Clinic identity on the public page** is the clinic's PUBLIC `display_name`, set by the Practice
  Owner (since 2026-10-08; until then it was derived from the slug). `tenants.legal_name` is
  CONFIDENTIAL (`01-tenancy-and-clinics/03-design.md`) and is never shown. The slug stays routing only,
  never an authorisation input: it selects which clinic's name and free slots are read.
- **`docs/features/05-patients/01-requirements.md`** lists "appointments, booking and intake" as out of
  scope for the patients MVP; this feature owns them in their own module and touches `patients` only
  through its service facade.
- **Audit catalogue** (`docs/features/04-audit-log/05-data-and-audit.md`): resource type `APPOINTMENT`,
  actions `appointment.create` (`patient_id`, `source`) and `appointment.state_change`
  (`from_state`, `to_state`). Reads are audited since T1-34 as `appointment.read`
  (registered 2026-10-08): the calendar with `query_filters` (`range`, `practitioner`) and
  `result_count`; a patient's bookings (`GET /patients/{id}/appointments`) with `patient_id`,
  `care_relationship_id` and `purpose`, under the treating-relationship rule (`403
  AUTHZ_CARE_RELATIONSHIP_DENIED` for a doctor or nurse off the patient's care team, `404` across
  tenants, both audited `DENIED`).
- **Deferred:** CAPTCHA (a new third-party data flow, needs its own decision); SMS confirmations;
  rate limits are in-process (`app/core/rate_limit.py` notes). Email confirmations and reminders were
  added on 2026-10-08 (above).
- **Availability is tenant configuration** (above) is superseded by "Clinic hours, slot length and
  booking emails" for the shape of the table and the slot step.
