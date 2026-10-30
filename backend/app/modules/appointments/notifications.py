"""The booking emails: a confirmation when a booking is made, a reminder 24 hours before.

Contract: `docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours, slot length and booking
emails". Scheduling: `docs/reference/decisions/D-009-scheduled-jobs-and-booking-reminders.md`.

The booking writes its rows into `appointment_notifications` on its own transaction
(`service._enqueue_notifications`). This module sends what is due, one tenant per transaction::

    cd backend && uv run python -m app.modules.appointments.notifications send-due [--tenant-id <uuid>]

With outgoing email not configured the command changes nothing and exits `2`, so a scheduler never
reads a no-op as success.

## Never twice

1. **Claim** due `PENDING` rows `FOR UPDATE SKIP LOCKED` (two runs never take one row), decide on
   the same transaction which to skip (a booking that is not live or has started, a patient with no
   address: `SKIPPED` with a code) and mark the rest `SENDING`. Commit.
2. **Send** each, outside any transaction.
3. **Record** each outcome on a transaction of its own: `SENT`; or, for a refusal, back to `PENDING`
   five minutes later until the third attempt, then `FAILED`. Each send is audited
   `integration.request` (`provider: SMTP`, `outcome_class`).

A run that dies between 1 and 3 leaves its rows `SENDING`, and nothing ever sends a `SENDING` row
again: delivery is **at most once**. With `UNIQUE (tenant_id, appointment_id, kind)` that is the
guarantee "never two reminders for one booking". A missed reminder is the accepted cost.

## What an email says, and what it never says

The clinic's display name (PUBLIC), the date and time in Sydney, the reference and how to change it.
Never the patient's name, the visit type, the practitioner or anything clinical; every value is
HTML-escaped. Nothing about the recipient or the server's reply reaches a log line or the audit
trail: the outcome is recorded as a code.
"""

import argparse
import html
import logging
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text
from sqlmodel import Session

from app import utils
from app.core.config import settings
from app.core.db import engine, tenant_transaction
from app.modules.appointments.schemas import NotificationRunReport
from app.modules.appointments.service import TIMEZONE, booking_reference
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as identity_tenancy
from app.modules.patients import service as patients

logger = logging.getLogger(__name__)

# The role the job writes its audit events under: there is no human actor.
SYSTEM_ROLE: Final[str] = "SYSTEM_NOTIFICATIONS"
MAX_ATTEMPTS: Final[int] = 3
BATCH: Final[int] = 100
EXIT_EMAIL_NOT_CONFIGURED: Final[int] = 2
# A booking in one of these states is still to happen; anything else is not reminded or confirmed.
LIVE_STATUSES: Final[frozenset[str]] = frozenset({"BOOKED", "CONFIRMED"})

_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT n.id FROM appointment_notifications n
        WHERE n.tenant_id = :tenant_id
          AND n.status = 'PENDING'
          AND n.due_at <= now()
          AND (CAST(:appointment_id AS uuid) IS NULL OR n.appointment_id = :appointment_id)
          AND (CAST(:kind AS text) IS NULL OR n.kind = :kind)
        ORDER BY n.due_at, n.id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE appointment_notifications n
    SET status = 'SENDING', claimed_at = now(), attempts = n.attempts + 1, updated_at = now()
    FROM due WHERE n.id = due.id
    RETURNING n.id, n.appointment_id, n.kind, n.attempts
    """
)
# What the email needs from each booking, with the date and time already in Sydney (R7) and read on
# the database clock, so "has it started?" and the wording agree.
_BOOKINGS_SQL = text(
    """
    SELECT a.id, a.patient_id, a.status, a.starts_at > now() AS ahead,
           to_char(a.starts_at AT TIME ZONE :zone, 'FMDay FMDD FMMonth YYYY') AS day,
           to_char(a.starts_at AT TIME ZONE :zone, 'FMHH12:MI am') AS time
    FROM appointments a
    WHERE a.tenant_id = :tenant_id AND a.id = ANY(CAST(:ids AS uuid[]))
    """
)
_SKIP_SQL = text(
    "UPDATE appointment_notifications SET status = 'SKIPPED', outcome = :outcome,"
    " updated_at = now() WHERE tenant_id = :tenant_id AND id = :id AND status = 'SENDING'"
)
_SENT_SQL = text(
    "UPDATE appointment_notifications SET status = 'SENT', outcome = NULL, sent_at = now(),"
    " updated_at = now() WHERE tenant_id = :tenant_id AND id = :id AND status = 'SENDING'"
)
_RETRY_SQL = text(
    "UPDATE appointment_notifications SET status = 'PENDING', outcome = 'SMTP_ERROR',"
    " due_at = now() + interval '5 minutes', updated_at = now()"
    " WHERE tenant_id = :tenant_id AND id = :id AND status = 'SENDING'"
)
_FAILED_SQL = text(
    "UPDATE appointment_notifications SET status = 'FAILED', outcome = 'SMTP_ERROR',"
    " updated_at = now() WHERE tenant_id = :tenant_id AND id = :id AND status = 'SENDING'"
)


class EmailNotConfigured(RuntimeError):
    """Outgoing email is off: nothing was claimed and nothing was sent."""


@dataclass(frozen=True)
class _Email:
    notification_id: uuid.UUID
    attempts: int
    to: str
    subject: str
    html_content: str


def render(
    *, kind: str, clinic: str, day: str, time: str, reference: str
) -> tuple[str, str]:
    """The subject and HTML of one booking email. Only the four values the contract allows."""
    if kind == "REMINDER":
        heading = "Your appointment is tomorrow"
        lead = f"This is a reminder of your appointment with {clinic}."
        subject = f"Reminder: your appointment with {clinic}"
    else:
        heading = "Your appointment is booked"
        lead = f"Your appointment with {clinic} is booked."
        subject = f"Your appointment with {clinic} is booked"
    context = {
        "project_name": settings.PROJECT_NAME,
        "clinic": clinic,
        "heading": heading,
        "lead": lead,
        "preview": f"{day}, {time}. Reference {reference}.",
        "day": day,
        "time": time,
        "reference": reference,
    }
    # `render_email_template` does not autoescape, and the clinic name is typed by a person.
    html_content = utils.render_email_template(
        template_name="booking_notification.html",
        context={key: html.escape(value) for key, value in context.items()},
    )
    return subject, html_content


def _claim(
    *,
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID | None,
    kind: str | None,
    report: NotificationRunReport,
) -> list[_Email]:
    """Step 1: claim what is due, skip what must not be sent, and prepare the rest."""
    with tenant_transaction(tenant_id=tenant_id, actor_role=SYSTEM_ROLE) as session:
        connection = session.connection()
        claimed = connection.execute(
            _CLAIM_SQL,
            {
                "tenant_id": tenant_id,
                "appointment_id": appointment_id,
                "kind": kind,
                "limit": BATCH,
            },
        ).all()
        if not claimed:
            return []
        bookings = {
            row.id: row
            for row in connection.execute(
                _BOOKINGS_SQL,
                {
                    "tenant_id": tenant_id,
                    "zone": TIMEZONE,
                    "ids": [row.appointment_id for row in claimed],
                },
            )
        }
        addresses = patients.contact_emails(
            session,
            tenant_id=tenant_id,
            patient_ids=[booking.patient_id for booking in bookings.values()],
        )
        opted_out = patients.opted_out_ids(
            session,
            tenant_id=tenant_id,
            patient_ids=[booking.patient_id for booking in bookings.values()],
        )
        clinic = (
            identity_tenancy.tenant_display_name(session, tenant_id=tenant_id)
            or "your clinic"
        )
        emails: list[_Email] = []
        for notification_id, appointment_id_, notification_kind, attempts in claimed:
            booking = bookings.get(appointment_id_)
            outcome: str | None = None
            if booking is None or booking.status not in LIVE_STATUSES:
                outcome = "BOOKING_NOT_LIVE"
            elif not booking.ahead:
                outcome = "STARTED"
            elif booking.patient_id not in addresses:
                outcome = "NO_EMAIL"
            elif notification_kind == "REMINDER" and booking.patient_id in opted_out:
                outcome = "OPTED_OUT"
            if outcome is not None:
                connection.execute(
                    _SKIP_SQL,
                    {"tenant_id": tenant_id, "id": notification_id, "outcome": outcome},
                )
                report.skipped += 1
                continue
            assert booking is not None
            subject, html_content = render(
                kind=notification_kind,
                clinic=clinic,
                day=booking.day,
                time=booking.time,
                reference=booking_reference(booking.id),
            )
            emails.append(
                _Email(
                    notification_id=notification_id,
                    attempts=attempts,
                    to=addresses[booking.patient_id],
                    subject=subject,
                    html_content=html_content,
                )
            )
        return emails


def _record(
    *,
    tenant_id: uuid.UUID,
    email: _Email,
    accepted: bool,
    report: NotificationRunReport,
) -> None:
    """Step 3: the outcome and its `integration.request` event, on one transaction."""
    if accepted:
        statement, result, outcome_class = _SENT_SQL, "SUCCESS", "SENT"
        report.sent += 1
    elif email.attempts >= MAX_ATTEMPTS:
        statement, result, outcome_class = _FAILED_SQL, "FAILED", "FAILED"
        report.failed += 1
    else:
        statement, result, outcome_class = _RETRY_SQL, "FAILED", "RETRY"
        report.retried += 1
    with tenant_transaction(tenant_id=tenant_id, actor_role=SYSTEM_ROLE) as session:
        session.connection().execute(
            statement, {"tenant_id": tenant_id, "id": email.notification_id}
        )
        audit.record(
            session,
            audit.AuditEvent(
                action="integration.request",
                result=result,
                resource_id=email.notification_id,
                payload={"provider": "SMTP", "outcome_class": outcome_class},
            ),
        )


def send_due(
    *,
    tenant_id: uuid.UUID,
    appointment_id: uuid.UUID | None = None,
    kind: str | None = None,
    report: NotificationRunReport | None = None,
) -> NotificationRunReport:
    """Send one tenant's due booking emails (optionally one booking's, or one kind)."""
    if not settings.emails_enabled:
        raise EmailNotConfigured("outgoing email is not configured")
    report = report if report is not None else NotificationRunReport()
    for email in _claim(
        tenant_id=tenant_id, appointment_id=appointment_id, kind=kind, report=report
    ):
        accepted = utils.deliver_email(
            email_to=email.to, subject=email.subject, html_content=email.html_content
        )
        _record(tenant_id=tenant_id, email=email, accepted=accepted, report=report)
    return report


def send_due_for_every_tenant() -> NotificationRunReport:
    """The scheduled run: every active organisation, one tenant per transaction."""
    if not settings.emails_enabled:
        raise EmailNotConfigured("outgoing email is not configured")
    with Session(engine) as session:
        tenant_ids = identity_tenancy.active_tenant_ids(session)
    report = NotificationRunReport()
    for tenant_id in tenant_ids:
        send_due(tenant_id=tenant_id, report=report)
    return report


def send_confirmation(*, tenant_id: uuid.UUID, appointment_id: uuid.UUID) -> None:
    """Send one booking's confirmation right after the booking committed (a background task).

    Best effort: a failure is logged by class only (never the address or the server's reply) and
    leaves the row for the scheduled run, or, if it was claimed, `SENDING` (never sent twice).
    """
    if not settings.emails_enabled:
        return
    try:
        send_due(
            tenant_id=tenant_id, appointment_id=appointment_id, kind="CONFIRMATION"
        )
    except Exception as error:  # noqa: BLE001 - a background task must not raise into the server
        logger.warning(
            "booking confirmation not sent",
            extra={"error_class": type(error).__name__},
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.appointments.notifications"
    )
    parser.add_argument("job", choices=("send-due",))
    parser.add_argument("--tenant-id", type=uuid.UUID, default=None)
    args = parser.parse_args(argv)
    try:
        report = (
            send_due(tenant_id=args.tenant_id)
            if args.tenant_id is not None
            else send_due_for_every_tenant()
        )
    except EmailNotConfigured:
        sys.stderr.write("outgoing email is not configured: nothing was sent\n")
        return EXIT_EMAIL_NOT_CONFIGURED
    # Counts only: no identifier, address or time reaches the terminal.
    sys.stdout.write(report.model_dump_json() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - the command-line entry point
    sys.exit(main())
