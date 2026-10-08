"""Deny by default: the refusals come first (unauthenticated, unpermitted, cross-tenant, INV-1)."""

import uuid

from fastapi.testclient import TestClient

from tests.appointments.conftest import API, MONDAY_0900, AppointmentsApi, Clinic, code


def test_every_staff_route_refuses_an_unauthenticated_caller(
    client: TestClient,
) -> None:
    some_id = uuid.uuid4()
    for method, path in (
        ("GET", f"{API}/practitioners"),
        ("GET", f"{API}/appointments?from={MONDAY_0900}&to={MONDAY_0900}"),
        ("POST", f"{API}/appointments"),
        ("POST", f"{API}/appointments/{some_id}/status"),
        ("GET", f"{API}/patients/{some_id}/appointments"),
    ):
        assert client.request(method, path).status_code == 401, path


def test_a_role_without_patient_read_cannot_see_the_calendar(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    nobody = api.staff(clinic.owner, None)
    assert (
        api.client.get(f"{API}/practitioners", headers=nobody.headers).status_code
        == 403
    )
    assert api.window(nobody).status_code == 403
    assert (
        api.client.get(
            f"{API}/patients/{clinic.patient_id}/appointments", headers=nobody.headers
        ).status_code
        == 403
    )


def test_pharmacy_and_auditor_read_but_cannot_book_or_move_a_booking(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
    )
    assert booked.status_code == 201, booked.text
    for role in ("PHARMACY", "COMPLIANCE_AUDITOR"):
        reader = api.staff(clinic.owner, role)
        assert api.window(reader).status_code == 200
        refused = api.book(
            reader,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.doctor.user_id,
            starts_at="2030-03-04T10:00:00+11:00",
        )
        assert refused.status_code == 403
        assert code(refused) == "PERMISSION_NOT_HELD"
        assert (
            api.set_status(reader, booked.json()["id"], "CONFIRMED").status_code == 403
        )
    assert api.count("appointments", clinic.tenant_id) == 1


def test_reception_books_and_moves_bookings(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    reception = api.staff(clinic.owner, "ADMINISTRATOR")
    booked = api.book(
        reception, patient_id=clinic.patient_id, practitioner_id=clinic.doctor.user_id
    )
    assert booked.status_code == 201, booked.text
    assert (
        api.set_status(reception, booked.json()["id"], "CONFIRMED").status_code == 200
    )


def test_another_tenants_booking_patient_and_practitioner_are_404(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic()
    theirs = api.book(
        other.owner, patient_id=other.patient_id, practitioner_id=other.doctor.user_id
    ).json()

    # Their appointment: absent for us, untouched for them.
    moved = api.set_status(clinic.owner, theirs["id"], "CANCELLED")
    assert moved.status_code == 404
    assert code(moved) == "APPOINTMENT_NOT_FOUND"
    assert theirs["id"] not in moved.text

    # Their patient and their practitioner cannot be named in our booking.
    with_their_patient = api.book(
        clinic.owner, patient_id=other.patient_id, practitioner_id=clinic.doctor.user_id
    )
    assert with_their_patient.status_code == 404
    assert code(with_their_patient) == "PATIENT_NOT_FOUND"
    with_their_doctor = api.book(
        clinic.owner, patient_id=clinic.patient_id, practitioner_id=other.doctor.user_id
    )
    assert with_their_doctor.status_code == 404
    assert code(with_their_doctor) == "PRACTITIONER_NOT_FOUND"

    history = api.client.get(
        f"{API}/patients/{other.patient_id}/appointments", headers=clinic.owner.headers
    )
    assert history.status_code == 404

    # Our calendar does not contain their booking, and theirs is still BOOKED.
    assert api.window(clinic.owner).json() == []
    assert api.window(other.owner).json()[0]["status"] == "BOOKED"
    ours = api.client.get(f"{API}/practitioners", headers=clinic.owner.headers).json()
    assert str(other.doctor.user_id) not in {p["id"] for p in ours}


def test_a_client_tenant_id_is_ignored_and_audited(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    other = api.clinic()
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        tenant_id=str(other.tenant_id),
    )
    assert booked.status_code == 201, booked.text
    assert api.count("appointments", clinic.tenant_id) == 1
    assert api.count("appointments", other.tenant_id) == 0
    denied = [
        event
        for event in api.audit(clinic.tenant_id, "appointment.create")
        if event["result"] == "DENIED"
    ]
    assert [event["reason"] for event in denied] == ["CLIENT_TENANT_ID_IGNORED"]
    assert denied[0]["actor_id"] == clinic.owner.user_id


def test_server_decided_fields_are_refused_in_the_body(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    for field, value in (
        ("status", "COMPLETED"),
        ("ends_at", "2030-03-04T12:00:00+11:00"),
        ("source", "PUBLIC_BOOKING"),
        ("created_by", str(uuid.uuid4())),
    ):
        refused = api.book(
            clinic.owner,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.doctor.user_id,
            **{field: value},
        )
        assert refused.status_code == 422, field
    naive = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at="2030-03-04T09:00:00",
    )
    assert naive.status_code == 422
    assert api.count("appointments", clinic.tenant_id) == 0
