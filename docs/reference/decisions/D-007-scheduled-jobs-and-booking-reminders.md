# D-007: Scheduled jobs (booking reminders) run from a transactional outbox, triggered by a scheduler the owner enables

- **Status:** Accepted for the mechanism · **OPEN** for the trigger (the owner must enable it)
- **Date:** 2026-10-08
- **Owner:** CTO (mechanism) · Practice Owner / platform owner (enabling the trigger)
- **Source contract reference:** `docs/README.md` rule 7 ("one API, one worker"); `docs/features/01-tenancy-and-clinics/03-design.md` "Tenancy channels" (cron jobs: tenant in the envelope, one tenant per transaction, never one query across all tenants); `docs/features/13-integration-boundaries/03-design.md` (outbox, background deadline).

## Context

A booking reminder must be sent at a time nobody is making a request: about a day before the
appointment. The source contract assumes one API and **one worker**. This deployment (FastAPI Cloud +
Neon) runs the API only: there is no worker process, no queue and no cron. The prescriptions module
already met the same gap with a transactional outbox and a command-line drain
(`backend/app/modules/prescriptions/outbox.py`).

## Decision

1. **Outbox.** A booking writes its notifications on the booking's own transaction:
   `appointment_notifications` rows, one `CONFIRMATION` due now and one `REMINDER` due 24 hours before
   the start (only when that is still in the future). `UNIQUE (tenant_id, appointment_id, kind)` makes a
   second reminder for one booking unrepresentable. Rows are written only while outgoing email is
   configured (`settings.emails_enabled`).
2. **Confirmation, in process.** After the booking commits, the route sends that booking's confirmation
   as a background task. If the send fails, the row stays due and the next run of the job sends it.
3. **Reminders, by an idempotent job.** `send_due` claims due rows `FOR UPDATE SKIP LOCKED`, marks them
   `SENDING` and commits **before** sending, then records `SENT`. A crash after a send leaves the row
   `SENDING`, which is never sent again: delivery is **at most once** (a missed reminder is preferred to
   a duplicate). An SMTP refusal returns the row to `PENDING` for a retry, at most 3 attempts, then
   `FAILED`. A cancelled, no-show, arrived or completed booking, a booking that has started, and a
   patient with no email address are `SKIPPED` with a code. One tenant per transaction; the only
   cross-tenant read is the list of active tenant ids (`tenants` is global).
4. **Triggers, all existing infrastructure:**
   - CLI: `cd backend && uv run python -m app.modules.appointments.notifications send-due [--tenant-id <uuid>]`
     (exit `2` when email is not configured, so a no-op is never read as success);
   - a protected endpoint, `POST /api/v1/internal/booking-notifications/run`, enabled only when
     `BOOKING_NOTIFICATIONS_RUN_TOKEN` is set (otherwise `404`), authorised by that bearer token
     (constant-time compare), rate-limited, answering counts only;
   - `.github/workflows/booking-reminders.yml`, a GitHub Actions schedule (every 15 minutes) that calls
     the endpoint. It is **inert** until the repository variable `BOOKING_REMINDERS_URL` is set.

## What the owner must do (OPEN)

To turn reminders on in production: generate a token (`python3 -c "import secrets;
print(secrets.token_urlsafe(48))"`), set it as `BOOKING_NOTIFICATIONS_RUN_TOKEN` in the FastAPI Cloud
environment and as the repository secret `BOOKING_REMINDERS_TOKEN`, and set the repository variable
`BOOKING_REMINDERS_URL` to `https://<production host>/api/v1/internal/booking-notifications/run`.
Until then confirmations are sent (in process) and reminders wait in the outbox; a reminder whose
appointment has started is skipped, never sent late. GitHub's scheduler can run late under load; a
dedicated worker (the source's shape) would replace the workflow without changing the outbox.

## Alternatives considered

- **A third-party scheduler or queue** (Cloud Scheduler, SQS, a cron SaaS): refused, a new third-party
  data flow and a new service.
- **APScheduler or a thread inside the API process**: FastAPI Cloud scales instances up and down and
  to zero; an in-process timer fires on every instance or on none. The outbox claim would keep it
  idempotent, but not reliable.
- **Send the reminder at booking time with a delayed-delivery SMTP header**: not portable, and a
  cancelled booking could not be withdrawn.
