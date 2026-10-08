"""The calendar: roster, booking, overlap refusal, the status machine and the reads."""

from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.db import engine
from tests.appointments.conftest import (
    API,
    MONDAY_0905,
    MONDAY_0915,
    AppointmentsApi,
    Clinic,
    code,
)


def test_practitioners_are_active_doctors_prescribers_and_nurses(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    prescriber = api.staff(
        clinic.owner, "AUTHORISED_PRESCRIBER", full_name="Dr Ash Example"
    )
    api.staff(clinic.owner, "ADMINISTRATOR", full_name="Reception Example")
    roster = api.client.get(f"{API}/practitioners", headers=clinic.owner.headers).json()
    assert {(p["name"], p["role"], p["title"]) for p in roster} == {
        ("Dr Wren Example", "DOCTOR", "Doctor"),
        ("Dr Ash Example", "DOCTOR", "Authorised Prescriber"),
        ("Kit Example, RN", "NURSE", "Nurse"),
    }
    # The owner (PRACTICE_OWNER only) is not bookable; an inactive account is not either.
    assert str(clinic.owner.user_id) not in {p["id"] for p in roster}
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE "user" SET is_active = false WHERE id = :id'),
            {"id": prescriber.user_id},
        )
    roster = api.client.get(f"{API}/practitioners", headers=clinic.owner.headers).json()
    assert "Dr Ash Example" not in {p["name"] for p in roster}


def test_a_booking_gets_its_end_from_its_type_and_is_audited(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        type="INITIAL_CONSULT",
    )
    assert booked.status_code == 201, booked.text
    body = booked.json()
    assert body["status"] == "BOOKED"
    assert body["source"] == "STAFF"
    assert body["patient_name"] == "Ada Synthetic"
    starts = datetime.fromisoformat(body["starts_at"])
    assert datetime.fromisoformat(body["ends_at"]) - starts == timedelta(minutes=30)

    [event] = api.audit(clinic.tenant_id, "appointment.create")
    assert event["result"] == "SUCCESS"
    assert str(event["resource_id"]) == body["id"]
    assert event["actor_id"] == clinic.owner.user_id
    assert event["metadata"] == {
        "patient_id": str(clinic.patient_id),
        "source": "STAFF",
    }


def test_the_type_must_match_the_practitioners_role(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    refused = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.nurse.user_id,
        type="INITIAL_CONSULT",
    )
    assert refused.status_code == 422
    assert code(refused) == "TYPE_NOT_OFFERED"
    nurse = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.nurse.user_id,
        type="NURSE_TRIAGE",
    )
    assert nurse.status_code == 201


def test_a_double_booking_is_refused_and_names_the_clash_without_the_patient(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    first = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    )
    assert first.status_code == 201
    clash = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at=MONDAY_0905,
    )
    assert clash.status_code == 409
    assert code(clash) == "APPOINTMENT_OVERLAP"
    assert clash.json()["detail"]["message"] == (
        "Dr Wren Example is already booked from 09:00 to 09:15."
    )
    assert "Synthetic" not in clash.text and "Ada" not in clash.text
    # Back to back is not an overlap: the range is half-open.
    assert (
        api.book(
            clinic.owner,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.doctor.user_id,
            starts_at=MONDAY_0915,
        ).status_code
        == 201
    )
    # Another practitioner at the same time is free.
    assert (
        api.book(
            clinic.owner,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.nurse.user_id,
            type="NURSE_TRIAGE",
        ).status_code
        == 201
    )
    assert len(api.audit(clinic.tenant_id, "appointment.create")) == 3


def test_a_cancelled_or_no_show_booking_frees_its_slot(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    for released in ("CANCELLED", "NO_SHOW"):
        booked = api.book(
            clinic.owner,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.doctor.user_id,
        ).json()
        assert api.set_status(clinic.owner, booked["id"], released).status_code == 200
    again = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    )
    assert again.status_code == 201


def test_the_status_machine_and_its_audit(api: AppointmentsApi, clinic: Clinic) -> None:
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    ).json()
    for step in ("CONFIRMED", "ARRIVED", "COMPLETED"):
        moved = api.set_status(clinic.owner, booked["id"], step)
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == step

    for illegal in ("BOOKED", "CANCELLED", "COMPLETED"):
        refused = api.set_status(clinic.owner, booked["id"], illegal)
        assert refused.status_code == 409
        assert code(refused) == "ILLEGAL_STATE_TRANSITION"

    events = api.audit(clinic.tenant_id, "appointment.state_change")
    assert [e["metadata"] for e in events] == [
        {"from_state": "BOOKED", "to_state": "CONFIRMED"},
        {"from_state": "CONFIRMED", "to_state": "ARRIVED"},
        {"from_state": "ARRIVED", "to_state": "COMPLETED"},
    ]
    assert api.set_status(clinic.owner, booked["id"], "LOST").status_code == 422


def test_booked_cannot_skip_to_completed(api: AppointmentsApi, clinic: Clinic) -> None:
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    ).json()
    assert api.set_status(clinic.owner, booked["id"], "COMPLETED").status_code == 409


def test_the_window_read_filters_and_bounds(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    )
    api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.nurse.user_id,
        type="NURSE_TRIAGE",
        starts_at="2030-03-04T11:00:00+11:00",
    )
    # Next day: outside the window.
    api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at="2030-03-05T09:00:00+11:00",
    )
    day = api.window(clinic.owner).json()
    assert [a["starts_at"] for a in day] == sorted(a["starts_at"] for a in day)
    assert len(day) == 2
    doctor_only = api.window(
        clinic.owner, practitioner_id=str(clinic.doctor.user_id)
    ).json()
    assert len(doctor_only) == 1

    backwards = api.window(
        clinic.owner,
        **{"from": "2030-03-05T00:00:00+11:00", "to": "2030-03-04T00:00:00+11:00"},
    )
    assert backwards.status_code == 422
    assert code(backwards) == "INVALID_RANGE"
    too_wide = api.window(clinic.owner, to="2030-05-04T00:00:00+11:00")
    assert code(too_wide) == "INVALID_RANGE"
    assert api.window(clinic.owner, to="2030-03-05T00:00:00").status_code == 422


def test_a_patients_history_is_newest_first(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    )
    api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at="2030-03-06T09:00:00+11:00",
    )
    history = api.client.get(
        f"{API}/patients/{clinic.patient_id}/appointments", headers=clinic.owner.headers
    )
    assert history.status_code == 200
    starts = [a["starts_at"] for a in history.json()]
    assert starts == sorted(starts, reverse=True) and len(starts) == 2
