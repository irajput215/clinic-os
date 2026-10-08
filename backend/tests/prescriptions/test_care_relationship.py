"""T1-34 across the patient's other tabs: scripts, bookings and TGA approvals, staging, and the
practice-wide reads that are now audited.

A patient's scripts, bookings and approvals are part of the patient's record, so a doctor or nurse
reaches them only through an active care relationship (decision D-007): `403
AUTHZ_CARE_RELATIONSHIP_DENIED` and a `DENIED` event without one, `404` across a tenant boundary, and
`care_relationship_id` with `purpose` on the read event with one. Staging a script needs the same
relationship (`11-prescribing` US-1).
"""

from app.core.config import settings
from tests.prescriptions.conftest import Clinic, RxApi, code
from tests.utils.care import relate

API = settings.API_V1_STR
CODE = "AUTHZ_CARE_RELATIONSHIP_DENIED"


def _patient_reads(
    rx: RxApi, clinic: Clinic, actor_headers: dict[str, str]
) -> list[int]:
    patient = clinic.patient_id
    return [
        rx.client.get(
            f"{API}/prescriptions",
            params={"patient_id": str(patient)},
            headers=actor_headers,
        ).status_code,
        rx.client.get(
            f"{API}/patients/{patient}/appointments", headers=actor_headers
        ).status_code,
        rx.client.get(
            f"{API}/patients/{patient}/tga-approvals", headers=actor_headers
        ).status_code,
    ]


def test_a_doctor_off_the_care_team_is_refused_every_patient_tab_and_staging(
    rx: RxApi, clinic: Clinic
) -> None:
    rx.stage(clinic)
    doctor = clinic.verifier  # a Doctor-only account

    assert _patient_reads(rx, clinic, doctor.headers) == [403, 403, 403]
    staged = rx.stage_raw(doctor, clinic)
    assert staged.status_code == 403
    assert code(staged) == CODE

    assert clinic.owner.tenant_id is not None
    for action in (
        "prescription.read",
        "appointment.read",
        "tga_approval.read",
        "prescription.create",
    ):
        [denied] = [
            row
            for row in rx.audit(clinic.owner.tenant_id, action)
            if row["actor_id"] == doctor.user_id
        ]
        assert (denied["result"], denied["reason"]) == ("DENIED", CODE), action


def test_another_tenants_patient_stays_404_on_the_tabs(
    rx: RxApi, clinic: Clinic
) -> None:
    other = rx.clinic("Other Rx Clinic")
    relate(
        rx.client,
        other.owner.headers,
        patient_id=other.patient_id,
        practitioner_id=other.verifier.user_id,
    )
    statuses = [
        rx.client.get(
            f"{API}/patients/{clinic.patient_id}/appointments",
            headers=other.verifier.headers,
        ).status_code,
        rx.client.get(
            f"{API}/patients/{clinic.patient_id}/tga-approvals",
            headers=other.verifier.headers,
        ).status_code,
    ]
    assert statuses == [404, 404]
    # The scripts list is a filter: another organisation's patient matches nothing, and says nothing.
    listed = rx.client.get(
        f"{API}/prescriptions",
        params={"patient_id": str(clinic.patient_id)},
        headers=other.verifier.headers,
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_on_the_care_team_the_tabs_open_and_record_the_relationship(
    rx: RxApi, clinic: Clinic
) -> None:
    rx.stage(clinic)
    doctor = clinic.verifier
    relationship = relate(
        rx.client,
        clinic.owner.headers,
        patient_id=clinic.patient_id,
        practitioner_id=doctor.user_id,
    )

    assert _patient_reads(rx, clinic, doctor.headers) == [200, 200, 200]
    assert rx.stage_raw(doctor, clinic).status_code == 201

    assert clinic.owner.tenant_id is not None
    for action in ("prescription.read", "appointment.read", "tga_approval.read"):
        [read] = [
            row
            for row in rx.audit(clinic.owner.tenant_id, action)
            if row["actor_id"] == doctor.user_id
        ]
        assert read["result"] == "SUCCESS"
        assert read["payload"]["patient_id"] == str(clinic.patient_id)
        assert read["payload"]["care_relationship_id"] == str(relationship), action
        assert read["payload"]["purpose"] == "TREATMENT"


def test_the_queue_the_calendar_and_today_are_audited_reads(
    rx: RxApi, clinic: Clinic
) -> None:
    owner = clinic.owner
    assert (
        rx.client.get(f"{API}/prescriptions", headers=owner.headers).status_code == 200
    )
    assert (
        rx.client.get(
            f"{API}/appointments",
            params={
                "from": "2026-10-01T00:00:00+10:00",
                "to": "2026-10-08T00:00:00+10:00",
            },
            headers=owner.headers,
        ).status_code
        == 200
    )
    assert (
        rx.client.get(f"{API}/dashboard/today", headers=owner.headers).status_code
        == 200
    )

    assert owner.tenant_id is not None
    queue, today_scripts = rx.audit(owner.tenant_id, "prescription.read")
    assert queue["payload"] == {"query_filters": [], "result_count": 0}
    assert today_scripts["payload"] == {
        "query_filters": ["actionable"],
        "result_count": 0,
    }
    calendar, today_bookings = rx.audit(owner.tenant_id, "appointment.read")
    assert calendar["payload"] == {"query_filters": ["range"], "result_count": 0}
    assert today_bookings["payload"] == {"query_filters": ["today"], "result_count": 0}
