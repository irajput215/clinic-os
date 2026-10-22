"""The booking emails: confirmation and reminder (`app.modules.appointments.notifications`).

Contract: `docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours, slot length and booking
emails"; scheduling: D-009. Mail goes to the in-memory sink (`tests/conftest.py` `mail_sink`), never
to a server. Denial and refusal paths first: email off, the job endpoint's token, skipped bookings;
then sending, idempotency, retries, and what an email may and may not carry.
"""

import logging
import threading
import uuid
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import engine
from app.modules.appointments import notifications
from app.modules.appointments.service import booking_reference
from tests.appointments.conftest import (
    API,
    MONDAY_0900,
    AppointmentsApi,
    Clinic,
)
from tests.conftest import MailSink

RUN_URL = f"{API}/internal/booking-notifications/run"
TOKEN = "t" * 48
PATIENT_EMAIL = "nora.quinn@example.com"


def _rows(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT n.id, n.appointment_id, n.kind, n.status, n.outcome, n.attempts,"
                " n.due_at, a.starts_at, n.created_at"
                " FROM appointment_notifications n JOIN appointments a ON a.id = n.appointment_id"
                " WHERE n.tenant_id = :t ORDER BY n.kind, n.created_at"
            ),
            {"t": tenant_id},
        ).mappings()
        return [dict(row) for row in rows]


def _make_due(tenant_id: uuid.UUID, kind: str = "REMINDER") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE appointment_notifications SET due_at = now() - interval '1 minute'"
                " WHERE tenant_id = :t AND kind = :k"
            ),
            {"t": tenant_id, "k": kind},
        )


def _public_booking(api: AppointmentsApi, clinic: Clinic, **overrides: Any) -> str:
    slot = api.slots(clinic.slug, "NURSE_TRIAGE").json()[0]
    booked = api.public_book(clinic.slug, slot, **overrides)
    assert booked.status_code == 201, booked.text
    return str(booked.json()["reference"])


def _staff_booking(api: AppointmentsApi, clinic: Clinic, patient_id: uuid.UUID) -> str:
    booked = api.book(
        clinic.owner,
        patient_id=patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at=MONDAY_0900,
    )
    assert booked.status_code == 201, booked.text
    return str(booked.json()["id"])


def _patient_with_email(api: AppointmentsApi, clinic: Clinic, email: str) -> uuid.UUID:
    created = api.client.post(
        f"{API}/patients",
        json={
            "given_name": "Ivy",
            "family_name": "Mailable",
            "date_of_birth": "1985-05-05",
            "email": email,
        },
        headers=clinic.owner.headers,
    )
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()["id"])


def _integration_events(api: AppointmentsApi, clinic: Clinic) -> list[dict[str, Any]]:
    return api.audit(clinic.tenant_id, "integration.request")


# --- Refusals and the job's door ---------------------------------------------------------------


def test_with_email_off_nothing_is_queued_or_sent(
    api: AppointmentsApi,
    clinic: Clinic,
    mail_sink: MailSink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    _public_booking(api, clinic)
    assert _rows(clinic.tenant_id) == []
    assert mail_sink.sent == []
    with pytest.raises(notifications.EmailNotConfigured):
        notifications.send_due(tenant_id=clinic.tenant_id)
    assert notifications.main(["send-due", "--tenant-id", str(clinic.tenant_id)]) == 2


def test_the_job_endpoint_is_off_without_a_token(api: AppointmentsApi) -> None:
    assert settings.BOOKING_NOTIFICATIONS_RUN_TOKEN is None
    response = api.client.post(RUN_URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 404


def test_the_job_endpoint_refuses_a_wrong_or_missing_token(
    api: AppointmentsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "BOOKING_NOTIFICATIONS_RUN_TOKEN", SecretStr(TOKEN))
    for headers in (
        {},
        {"Authorization": f"Bearer {TOKEN[:-1]}"},
        {"Authorization": f"Basic {TOKEN}"},
        {"Authorization": TOKEN},
    ):
        response = api.client.post(RUN_URL, headers=headers)
        assert response.status_code == 401, headers
        assert TOKEN not in response.text


def test_the_job_endpoint_says_when_email_is_off(
    api: AppointmentsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "BOOKING_NOTIFICATIONS_RUN_TOKEN", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    response = api.client.post(RUN_URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EMAIL_NOT_CONFIGURED"


def test_a_cancelled_booking_is_never_reminded(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    patient = _patient_with_email(api, clinic, "cancel.me@example.com")
    appointment_id = _staff_booking(api, clinic, patient)
    assert api.set_status(clinic.owner, appointment_id, "CANCELLED").status_code == 200
    _make_due(clinic.tenant_id)

    report = notifications.send_due(tenant_id=clinic.tenant_id)

    assert report.sent == 0 and report.skipped == 1
    reminder = next(r for r in _rows(clinic.tenant_id) if r["kind"] == "REMINDER")
    assert (reminder["status"], reminder["outcome"]) == ("SKIPPED", "BOOKING_NOT_LIVE")
    assert [m["subject"] for m in mail_sink.to("cancel.me@example.com")] == [
        f"Your appointment with {_clinic_name(clinic)} is booked"
    ], "only the confirmation, sent before the cancellation"


def test_a_patient_without_an_email_is_skipped(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    _staff_booking(api, clinic, clinic.patient_id)  # the fixture patient has no address
    rows = _rows(clinic.tenant_id)
    confirmation = next(r for r in rows if r["kind"] == "CONFIRMATION")
    assert (confirmation["status"], confirmation["outcome"]) == ("SKIPPED", "NO_EMAIL")
    assert mail_sink.sent == []


def test_a_booking_that_has_started_is_not_reminded(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    patient = _patient_with_email(api, clinic, "late@example.com")
    with engine.begin() as conn:
        appointment_id = conn.execute(
            text(
                "INSERT INTO appointments (tenant_id, patient_id, practitioner_id, type, status,"
                " source, starts_at, ends_at, created_at, updated_at) VALUES (:t, :p, :d,"
                " 'FOLLOW_UP', 'BOOKED', 'STAFF', now() - interval '1 hour',"
                " now() - interval '45 minutes', now(), now()) RETURNING id"
            ),
            {"t": clinic.tenant_id, "p": patient, "d": clinic.doctor.user_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO appointment_notifications (tenant_id, appointment_id, kind, status,"
                " due_at, attempts, created_at, updated_at) VALUES (:t, :a, 'REMINDER',"
                " 'PENDING', now() - interval '1 day', 0, now(), now())"
            ),
            {"t": clinic.tenant_id, "a": appointment_id},
        )
    report = notifications.send_due(tenant_id=clinic.tenant_id)
    assert (report.sent, report.skipped) == (0, 1)
    assert _rows(clinic.tenant_id)[0]["outcome"] == "STARTED"
    assert mail_sink.sent == []


# --- Sending -----------------------------------------------------------------------------------


def _clinic_name(clinic: Clinic) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT display_name FROM tenants WHERE id = :id"),
                {"id": clinic.tenant_id},
            ).scalar_one()
        )


def test_a_public_booking_is_confirmed_at_once_with_the_minimum(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    reference = _public_booking(api, clinic)

    (message,) = mail_sink.to(PATIENT_EMAIL)
    clinic_name = _clinic_name(clinic)
    assert message["subject"] == f"Your appointment with {clinic_name} is booked"
    body = message["html_content"]
    assert clinic_name in body
    assert reference in body
    assert "(Sydney time)" in body
    assert "To change or cancel this appointment, please contact" in body
    # Nothing about the patient or the visit beyond the time and the reference.
    for withheld in (
        "Nora",
        "Quinn",
        "1990",
        "0412",
        "555",
        "triage",
        "Triage",
        "Kit Example",
        "nurse",
        PATIENT_EMAIL,
    ):
        assert withheld not in body, withheld
        assert withheld not in message["subject"], withheld

    rows = _rows(clinic.tenant_id)
    confirmation = next(r for r in rows if r["kind"] == "CONFIRMATION")
    assert confirmation["status"] == "SENT"
    # A reminder is queued exactly when 24 hours before the start is still ahead.
    reminder = [r for r in rows if r["kind"] == "REMINDER"]
    lead_ahead = confirmation["starts_at"] - confirmation["created_at"]
    assert len(reminder) == (1 if lead_ahead.total_seconds() > 24 * 3600 else 0)
    (event,) = _integration_events(api, clinic)
    assert event["result"] == "SUCCESS"
    assert event["resource_id"] == confirmation["id"]
    assert event["metadata"] == {"provider": "SMTP", "outcome_class": "SENT"}


def test_a_staff_booking_is_confirmed_and_reminded_once(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    address = "ivy.mailable@example.com"
    patient = _patient_with_email(api, clinic, address)
    appointment_id = _staff_booking(api, clinic, patient)

    rows = _rows(clinic.tenant_id)
    assert sorted((r["kind"], r["status"]) for r in rows) == [
        ("CONFIRMATION", "SENT"),
        ("REMINDER", "PENDING"),
    ]
    reminder = next(r for r in rows if r["kind"] == "REMINDER")
    assert (reminder["starts_at"] - reminder["due_at"]).total_seconds() == 24 * 3600

    # Not due yet: a run sends nothing.
    assert notifications.send_due(tenant_id=clinic.tenant_id).sent == 0
    _make_due(clinic.tenant_id)
    first = notifications.send_due(tenant_id=clinic.tenant_id)
    second = notifications.send_due(tenant_id=clinic.tenant_id)

    assert (first.sent, second.sent) == (1, 0)
    subjects = [m["subject"] for m in mail_sink.to(address)]
    assert subjects == [
        f"Your appointment with {_clinic_name(clinic)} is booked",
        f"Reminder: your appointment with {_clinic_name(clinic)}",
    ]
    reminder_body = mail_sink.to(address)[1]["html_content"]
    assert "Monday 4 March 2030, 9:00 am (Sydney time)" in reminder_body
    assert booking_reference(uuid.UUID(appointment_id)) in reminder_body
    assert "Ivy" not in reminder_body and "Mailable" not in reminder_body


def test_two_concurrent_runs_send_one_reminder(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    address = "race@example.com"
    _staff_booking(api, clinic, _patient_with_email(api, clinic, address))
    _make_due(clinic.tenant_id)
    barrier = threading.Barrier(4)
    reports: list[Any] = []

    def run() -> None:
        barrier.wait()
        reports.append(notifications.send_due(tenant_id=clinic.tenant_id))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(report.sent for report in reports) == 1
    assert [m["subject"].startswith("Reminder") for m in mail_sink.to(address)].count(
        True
    ) == 1


def test_a_claimed_row_is_never_sent_again(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    """At most once: a run that died after claiming leaves `SENDING`, which nothing resends."""
    address = "crash@example.com"
    _staff_booking(api, clinic, _patient_with_email(api, clinic, address))
    _make_due(clinic.tenant_id)
    claimed = notifications._claim(
        tenant_id=clinic.tenant_id,
        appointment_id=None,
        kind=None,
        report=notifications.NotificationRunReport(),
    )
    assert len(claimed) == 1  # ... and the process "dies" here, before sending

    assert notifications.send_due(tenant_id=clinic.tenant_id).sent == 0
    reminder = next(r for r in _rows(clinic.tenant_id) if r["kind"] == "REMINDER")
    assert reminder["status"] == "SENDING"
    assert [m["subject"].startswith("Reminder") for m in mail_sink.to(address)].count(
        True
    ) == 0


def test_the_database_holds_one_reminder_per_booking(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    _staff_booking(api, clinic, _patient_with_email(api, clinic, "unique@example.com"))
    reminder = next(r for r in _rows(clinic.tenant_id) if r["kind"] == "REMINDER")
    with pytest.raises(
        IntegrityError, match="uq_appointment_notifications_one_per_kind"
    ):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO appointment_notifications (tenant_id, appointment_id, kind,"
                    " status, due_at, attempts, created_at, updated_at) VALUES (:t, :a,"
                    " 'REMINDER', 'PENDING', now(), 0, now(), now())"
                ),
                {"t": clinic.tenant_id, "a": reminder["appointment_id"]},
            )


def test_a_refused_send_is_retried_then_failed(
    api: AppointmentsApi, clinic: Clinic, mail_sink: MailSink
) -> None:
    mail_sink.accept = False
    address = "bounce@example.com"
    _staff_booking(api, clinic, _patient_with_email(api, clinic, address))
    confirmation = next(
        r for r in _rows(clinic.tenant_id) if r["kind"] == "CONFIRMATION"
    )
    assert (confirmation["status"], confirmation["attempts"]) == ("PENDING", 1)
    assert confirmation["outcome"] == "SMTP_ERROR"

    for _ in range(2):
        _make_due(clinic.tenant_id, "CONFIRMATION")
        notifications.send_due(tenant_id=clinic.tenant_id, kind="CONFIRMATION")
    confirmation = next(
        r for r in _rows(clinic.tenant_id) if r["kind"] == "CONFIRMATION"
    )
    assert (confirmation["status"], confirmation["attempts"]) == ("FAILED", 3)
    _make_due(clinic.tenant_id, "CONFIRMATION")
    assert (
        notifications.send_due(tenant_id=clinic.tenant_id, kind="CONFIRMATION").sent
        == 0
    )
    assert len(mail_sink.to(address)) == 3
    assert [
        e["metadata"]["outcome_class"] for e in _integration_events(api, clinic)
    ] == [
        "RETRY",
        "RETRY",
        "FAILED",
    ]


def test_the_job_endpoint_and_the_command_send_what_is_due(
    api: AppointmentsApi,
    clinic: Clinic,
    mail_sink: MailSink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BOOKING_NOTIFICATIONS_RUN_TOKEN", SecretStr(TOKEN))
    address = "scheduled@example.com"
    _staff_booking(api, clinic, _patient_with_email(api, clinic, address))
    _make_due(clinic.tenant_id)

    response = api.client.post(RUN_URL, headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200, response.text
    assert response.json()["sent"] >= 1
    assert set(response.json()) == {"sent", "skipped", "failed", "retried"}
    assert len(mail_sink.to(address)) == 2
    # Idempotent: the same call again sends nothing to this patient.
    api.client.post(RUN_URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert len(mail_sink.to(address)) == 2
    assert notifications.main(["send-due", "--tenant-id", str(clinic.tenant_id)]) == 0
    assert notifications.main(["send-due"]) == 0
    assert len(mail_sink.to(address)) == 2


def test_a_clinic_name_cannot_inject_markup() -> None:
    subject, body = notifications.render(
        kind="CONFIRMATION",
        clinic='<a href="https://evil.example">Evil</a> & Co',
        day="Monday 4 March 2030",
        time="9:00 am",
        reference="BK-ABC123",
    )
    assert "<a href" not in body
    assert "&lt;a href=&quot;https://evil.example&quot;&gt;" in body
    assert subject.startswith("Your appointment with")


def test_nothing_about_the_patient_reaches_the_logs(
    api: AppointmentsApi,
    clinic: Clinic,
    mail_sink: MailSink,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mail_sink.accept = False  # the failure path is the one that tempts a log line
    with caplog.at_level(logging.DEBUG):
        _public_booking(api, clinic)
        _make_due(clinic.tenant_id, "CONFIRMATION")
        notifications.send_due(tenant_id=clinic.tenant_id)
    logged = caplog.text
    for value in (PATIENT_EMAIL, "Nora", "Quinn", "0412 555 019", "1990-03-21"):
        assert value not in logged, value


def test_a_background_failure_is_logged_by_class_only(
    clinic: Clinic, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(**_kwargs: Any) -> None:
        raise RuntimeError(f"cannot reach {PATIENT_EMAIL}")

    monkeypatch.setattr(notifications, "send_due", explode)
    with caplog.at_level(logging.DEBUG):
        notifications.send_confirmation(
            tenant_id=clinic.tenant_id, appointment_id=uuid.uuid4()
        )
    assert "booking confirmation not sent" in caplog.text
    assert PATIENT_EMAIL not in caplog.text
