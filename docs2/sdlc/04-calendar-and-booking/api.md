# Calendar and booking: API

## Proposed endpoints (contract for the backend owner)

All follow the repo's non-negotiables: tenant from the session only, RLS on every table, `404` across tenants, audit in the same transaction, RFC 7807 errors with `detail.code`.

| Method | Path | Contract |
|---|---|---|
| `GET` | `/api/v1/practitioners` | Bookable staff resolved from users and roles: `[{id, name, role: DOCTOR|NURSE, title}]`. |
| `GET` | `/api/v1/appointments?from=&to=&practitioner_id=` | Appointments starting in `[from, to)`. Response `Appointment[]` (see `src/data/types.ts`). |
| `POST` | `/api/v1/appointments` | `{patient_id, practitioner_id, type, starts_at}`. The server computes `ends_at` from the type. **`409 APPOINTMENT_OVERLAP`** comes from a GiST exclusion: `EXCLUDE USING gist (tenant_id WITH =, practitioner_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&) WHERE (status NOT IN ('CANCELLED','NO_SHOW'))`. `422 TYPE_NOT_OFFERED`. |
| `POST` | `/api/v1/appointments/{id}/status` | `{status}`. `409 ILLEGAL_STATE_TRANSITION` per R4. Audited. |
| `GET` | `/api/v1/public/{clinic_slug}/slots?type=` | Unauthenticated and rate-limited. The tenant is resolved from the slug **server-side**; an unknown slug gives `404`. Returns `PublicSlot[]` for the next 14 days. |
| `POST` | `/api/v1/public/{clinic_slug}/bookings` | Unauthenticated, rate-limited per IP and per email, with CAPTCHA recommended. `PublicBookingRequest`. It creates or matches the patient (never returning whether one existed) and books. `201 {reference}`. `409 SLOT_TAKEN`. |
