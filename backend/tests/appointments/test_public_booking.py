"""The unauthenticated public booking routes: tenant from the slug, uniform 404, rate limits,
no disclosure of whether a patient existed, minimal PHI, JSON only, audited."""

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import engine
from tests.appointments.conftest import API, AppointmentsApi, Clinic, code


def _first_slot(
    api: AppointmentsApi, clinic: Clinic, type: str = "NURSE_TRIAGE"
) -> dict:
    slots = api.slots(clinic.slug, type)
    assert slots.status_code == 200, slots.text
    assert slots.json(), "a clinic with a practitioner offers slots"
    return slots.json()[0]


def test_unknown_malformed_and_suspended_slugs_are_one_uniform_404(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    suspended = api.clinic()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE tenants SET status = 'SUSPENDED' WHERE id = :id"),
            {"id": suspended.tenant_id},
        )
    slot = _first_slot(api, clinic)
    answers = []
    for slug in ("no-such-clinic-anywhere", "Bad_Slug!", suspended.slug):
        slots = api.slots(slug)
        booking = api.public_book(slug, slot)
        assert slots.status_code == 404 and booking.status_code == 404, slug
        answers.append((slots.json()["detail"], booking.json()["detail"]))
    assert len({str(a) for a in answers}) == 1
    assert api.count("appointments", suspended.tenant_id) == 0


def test_slots_offer_the_right_role_hours_and_days_and_hide_taken_times(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    triage = api.slots(clinic.slug, "NURSE_TRIAGE").json()
    consult = api.slots(clinic.slug, "INITIAL_CONSULT").json()
    assert {s["practitioner_id"] for s in triage} == {str(clinic.nurse.user_id)}
    assert {s["practitioner_id"] for s in consult} == {str(clinic.doctor.user_id)}
    assert {s["practitioner_name"] for s in consult} == {"Dr Wren Example"}
    for slot in consult:
        start = datetime.fromisoformat(slot["starts_at"])
        assert datetime.fromisoformat(slot["ends_at"]) - start == timedelta(minutes=30)
    # Every slot is tomorrow or later and within 14 days; never more than the clinic's hours allow.
    now = datetime.now().astimezone()
    starts = [datetime.fromisoformat(s["starts_at"]) for s in triage]
    assert min(starts) > now and max(starts) < now + timedelta(days=15)
    assert set(triage[0]) == {
        "practitioner_id",
        "practitioner_name",
        "starts_at",
        "ends_at",
    }

    # Booking a time removes it from the offer.
    taken = triage[0]
    assert api.public_book(clinic.slug, taken).status_code == 201
    again = api.slots(clinic.slug, "NURSE_TRIAGE").json()
    assert taken not in again
    assert api.slots(clinic.slug, "SURGERY").status_code == 422


def test_tenant_settings_override_the_default_hours(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    default = len(api.slots(clinic.slug).json())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO appointment_settings (tenant_id, opens_at, closes_at,"
                " working_days, created_at, updated_at)"
                " VALUES (:t, '09:00', '10:00', '{1,2,3,4,5,6,7}', now(), now())"
            ),
            {"t": clinic.tenant_id},
        )
    custom = api.slots(clinic.slug).json()
    # 14 days, every day, 09:00-10:00 in 15-minute triage slots: 4 a day.
    assert len(custom) == 14 * 4
    assert len(custom) != default


def test_a_public_booking_creates_the_patient_and_appears_on_the_calendar(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slot = _first_slot(api, clinic)
    booked = api.public_book(clinic.slug, slot)
    assert booked.status_code == 201, booked.text
    assert set(booked.json()) == {"reference"}
    assert booked.json()["reference"].startswith("BK-")

    start = datetime.fromisoformat(slot["starts_at"])
    calendar = api.window(
        clinic.owner,
        **{
            "from": (start - timedelta(hours=1)).isoformat(),
            "to": (start + timedelta(hours=1)).isoformat(),
        },
    ).json()
    [appointment] = [a for a in calendar if a["source"] == "PUBLIC_BOOKING"]
    assert appointment["patient_name"] == "Nora Quinn"
    assert appointment["status"] == "BOOKED"

    [patient_event] = api.audit(clinic.tenant_id, "patient.create")[-1:]
    assert patient_event["actor_id"] is None
    assert patient_event["actor_role"] == "PUBLIC_BOOKING"
    assert patient_event["source_ip"]
    [booking_event] = api.audit(clinic.tenant_id, "appointment.create")
    assert booking_event["metadata"] == {
        "patient_id": appointment["patient_id"],
        "source": "PUBLIC_BOOKING",
    }
    assert "Nora" not in str(booking_event) and "nora" not in str(patient_event)


def test_an_existing_patient_is_matched_and_the_answer_does_not_say_so(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slots = api.slots(clinic.slug).json()
    first = api.public_book(clinic.slug, slots[0])
    patients_after_first = api.count("patients", clinic.tenant_id)
    # Same person, different case: matched, not duplicated.
    second = api.public_book(
        clinic.slug, slots[1], given_name="NORA", email="Nora.Quinn@example.com"
    )
    assert first.status_code == second.status_code == 201
    assert set(first.json()) == set(second.json()) == {"reference"}
    assert api.count("patients", clinic.tenant_id) == patients_after_first
    # A different date of birth is a different person.
    third = api.public_book(clinic.slug, slots[2], date_of_birth="1991-03-21")
    assert third.status_code == 201
    assert api.count("patients", clinic.tenant_id) == patients_after_first + 1


def test_a_taken_slot_is_409_and_leaves_no_patient_behind(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slot = _first_slot(api, clinic)
    assert api.public_book(clinic.slug, slot).status_code == 201
    patients = api.count("patients", clinic.tenant_id)
    taken = api.public_book(
        clinic.slug, slot, given_name="Other", email="other@example.com"
    )
    assert taken.status_code == 409
    assert code(taken) == "SLOT_TAKEN"
    assert api.count("patients", clinic.tenant_id) == patients


def test_only_an_offered_slot_can_be_booked(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slot = _first_slot(api, clinic)
    start = datetime.fromisoformat(slot["starts_at"])
    for bad in (
        {**slot, "starts_at": (start + timedelta(minutes=5)).isoformat()},
        {**slot, "starts_at": (start - timedelta(days=30)).isoformat()},
        {
            **slot,
            "practitioner_id": str(clinic.doctor.user_id),
        },  # a doctor for a triage
        {**slot, "practitioner_id": str(clinic.owner.user_id)},  # not bookable at all
    ):
        refused = api.public_book(clinic.slug, bad)
        assert refused.status_code == 422
        assert code(refused) == "SLOT_NOT_OFFERED"
    other = api.clinic()
    elsewhere = api.public_book(other.slug, slot)  # our nurse, their page
    assert code(elsewhere) == "SLOT_NOT_OFFERED"
    assert api.count("appointments", clinic.tenant_id) == 0


def test_validation_minimal_phi_consent_and_age(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slot = _first_slot(api, clinic)
    for overrides in (
        {"consent": False},
        {"phone": "02 9999 9999"},
        {"email": "not-an-email"},
        {"given_name": ""},
        {"given_name": "<script>"},
        {"condition": "Chronic knee pain"},  # nothing clinical is accepted
        {"status": "CONFIRMED"},
    ):
        refused = api.public_book(clinic.slug, slot, **overrides)
        assert refused.status_code == 422, overrides
        assert "Chronic" not in refused.text
    minor = api.public_book(
        clinic.slug, slot, date_of_birth=f"{datetime.now().year - 10}-01-01"
    )
    assert minor.status_code == 422
    assert code(minor) == "BOOKING_AGE_NOT_MET"
    assert api.count("patients", clinic.tenant_id) == 1  # the fixture's patient only


def test_a_booking_must_be_json(api: AppointmentsApi, clinic: Clinic) -> None:
    for content_type, body in (
        ("text/plain", '{"type":"NURSE_TRIAGE"}'),
        ("application/x-www-form-urlencoded", "type=NURSE_TRIAGE"),
    ):
        refused = api.client.post(
            f"{API}/public/{clinic.slug}/bookings",
            content=body,
            headers={"content-type": content_type},
        )
        assert refused.status_code == 415
    assert api.count("appointments", clinic.tenant_id) == 0


def test_a_client_tenant_id_on_a_public_booking_is_ignored_and_audited(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic()
    slot = _first_slot(api, clinic)
    booked = api.public_book(clinic.slug, slot, tenant_id=str(other.tenant_id))
    assert booked.status_code == 201
    assert api.count("appointments", other.tenant_id) == 0
    denied = [
        e
        for e in api.audit(clinic.tenant_id, "appointment.create")
        if e["result"] == "DENIED"
    ]
    assert [e["reason"] for e in denied] == ["CLIENT_TENANT_ID_IGNORED"]


def test_bookings_are_limited_per_email_and_per_address(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slots = api.slots(clinic.slug).json()
    statuses = [
        api.public_book(
            clinic.slug, slots[i], given_name=f"Nora{chr(97 + i)}"
        ).status_code
        for i in range(6)
    ]
    assert statuses[:5] == [201] * 5
    assert statuses[5] == 429
    # A different email from the same address still has budget, until the address limit.
    statuses = [
        api.public_book(
            clinic.slug, slots[10 + i], email=f"person{i}@example.com"
        ).status_code
        for i in range(6)
    ]
    assert 429 in statuses
    limited = api.public_book(clinic.slug, slots[30], email="fresh@example.com")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"]


def test_slots_are_limited_per_address(api: AppointmentsApi, clinic: Clinic) -> None:
    answers = [api.slots(clinic.slug).status_code for _ in range(61)]
    assert answers[:60] == [200] * 60 and answers[60] == 429


def test_nothing_from_a_booking_reaches_the_logs(
    api: AppointmentsApi, clinic: Clinic, caplog: pytest.LogCaptureFixture
) -> None:
    slot = _first_slot(api, clinic)
    with caplog.at_level(logging.DEBUG):
        api.public_book(clinic.slug, slot, family_name="Distinctivesurname")
        api.public_book(clinic.slug, slot, family_name="Distinctivesurname")
    assert "Distinctivesurname" not in caplog.text
    assert "nora.quinn" not in caplog.text
