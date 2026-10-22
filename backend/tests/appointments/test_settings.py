"""Clinic hours and slot length: `GET`/`PUT /api/v1/appointment-settings`.

Contract: `docs2/sdlc/04-calendar-and-booking/api.md`, "Clinic hours, slot length and booking
emails". Reading is any member's (opening hours are PUBLIC); changing is `tenant:configure`
(Practice Owner), audited `tenant.config_changed` on the change's transaction.

Denial paths first, then validation, then success and what the settings drive (the public slots).
"""

import uuid
from datetime import datetime
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.modules.appointments import service
from tests.appointments.conftest import (
    API,
    MONDAY_0900,
    AppointmentsApi,
    Clinic,
    code,
    week,
)

URL = f"{API}/appointment-settings"
SYDNEY = ZoneInfo("Australia/Sydney")
ACTION = "tenant.config_changed"


def _rows(tenant_id: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        settings_row = conn.execute(
            text("SELECT slot_minutes FROM appointment_settings WHERE tenant_id = :t"),
            {"t": tenant_id},
        ).first()
        hours = conn.execute(
            text(
                "SELECT weekday, opens_at, closes_at FROM appointment_hours"
                " WHERE tenant_id = :t ORDER BY weekday"
            ),
            {"t": tenant_id},
        ).all()
    return {
        "slot_minutes": None if settings_row is None else settings_row[0],
        "hours": [tuple(row) for row in hours],
    }


TUESDAY_MORNING = week({2: ("10:00", "11:00")}, slot_minutes=30)


# --- Denial path -------------------------------------------------------------------------------


def test_no_session_is_401(api: AppointmentsApi) -> None:
    assert api.client.get(URL).status_code == 401
    assert api.client.put(URL, json=TUESDAY_MORNING).status_code == 401


def test_an_account_with_no_organisation_is_refused(api: AppointmentsApi) -> None:
    loner = api.rbac.register_tenant(clinic_name=None)
    for response in (
        api.client.get(URL, headers=loner.headers),
        api.client.put(URL, json=TUESDAY_MORNING, headers=loner.headers),
    ):
        assert response.status_code == 403
        assert code(response) == "NO_ORGANISATION"


@pytest.mark.parametrize(
    "role_code",
    ["ADMINISTRATOR", "DOCTOR", "NURSE", "COMPLIANCE_AUDITOR", "PHARMACY"],
)
def test_a_role_without_tenant_configure_is_403_audited_and_changes_nothing(
    api: AppointmentsApi, clinic: Clinic, role_code: str
) -> None:
    member = api.staff(clinic.owner, role_code)

    response = api.put_settings(member, TUESDAY_MORNING)

    assert response.status_code == 403, response.text
    assert code(response) == "PERMISSION_NOT_HELD"
    assert _rows(clinic.tenant_id) == {"slot_minutes": None, "hours": []}
    (event,) = api.audit(clinic.tenant_id, ACTION)
    assert (event["result"], event["reason"]) == ("DENIED", "PERMISSION_NOT_HELD")
    assert event["actor_id"] == member.user_id
    assert event["metadata"] == {
        "changed_fields": ["hours", "slot_minutes"],
        "step_up": False,
    }


def test_a_refusal_that_cannot_be_audited_fails_closed(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    with (
        patch.object(
            service.audit,
            "record",
            side_effect=service.audit.AuditWriteRefused("simulated"),
        ),
        pytest.raises(service.audit.AuditWriteRefused),
    ):
        api.put_settings(clinic.doctor, TUESDAY_MORNING)
    assert _rows(clinic.tenant_id)["slot_minutes"] is None


def test_another_tenant_is_never_written(api: AppointmentsApi, clinic: Clinic) -> None:
    """INV-1: a body or query `tenant_id` is ignored and audited; only the caller's own clinic
    changes, and the other organisation's settings and trail stay untouched."""
    other = api.clinic()
    body = {**TUESDAY_MORNING, "tenant_id": str(other.tenant_id)}

    response = api.put_settings(clinic.owner, body, tenant_id=str(other.tenant_id))

    assert response.status_code == 200, response.text
    assert _rows(clinic.tenant_id)["slot_minutes"] == 30
    assert _rows(other.tenant_id) == {"slot_minutes": None, "hours": []}
    assert [
        (e["result"], e["reason"]) for e in api.audit(clinic.tenant_id, ACTION)
    ] == [
        ("DENIED", "CLIENT_TENANT_ID_IGNORED"),
        ("SUCCESS", None),
    ]
    assert api.audit(other.tenant_id, ACTION) == []


# --- Validation --------------------------------------------------------------------------------


def _with_day(weekday: int, opens: Any, closes: Any, slot: int = 15) -> dict[str, Any]:
    body = week({1: ("09:00", "17:00")}, slot_minutes=slot)
    body["hours"][weekday - 1] = {
        "weekday": weekday,
        "opens_at": opens,
        "closes_at": closes,
    }
    return body


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (_with_day(2, "12:00", "09:00"), "Tuesday: closing must be after opening."),
        (_with_day(2, "09:00", "09:00"), "Tuesday: closing must be after opening."),
        (
            _with_day(3, "09:00", None),
            "Wednesday: give both an opening and a closing time.",
        ),
        (_with_day(4, "09:07", "12:00"), "Thursday: use times on 5-minute marks."),
        (
            _with_day(5, "09:00", "09:20", slot=30),
            "Friday: open for at least one 30-minute slot.",
        ),
        (week({}, slot_minutes=15), "Open the clinic on at least one day."),
    ],
)
def test_invalid_hours_are_422_naming_the_day(
    api: AppointmentsApi, clinic: Clinic, body: dict[str, Any], message: str
) -> None:
    response = api.put_settings(clinic.owner, body)
    assert response.status_code == 422, response.text
    assert message in response.text
    assert _rows(clinic.tenant_id)["slot_minutes"] is None
    assert api.audit(clinic.tenant_id, ACTION) == []


def _duplicate_day() -> dict[str, Any]:
    body = week({1: ("09:00", "17:00")})
    body["hours"][6] = {"weekday": 1, "opens_at": None, "closes_at": None}
    return body


@pytest.mark.parametrize(
    "body",
    [
        {**TUESDAY_MORNING, "slot_minutes": 25},
        {**TUESDAY_MORNING, "slot_minutes": 0},
        {**TUESDAY_MORNING, "hours": TUESDAY_MORNING["hours"][:6]},
        _duplicate_day(),
        {**TUESDAY_MORNING, "extra": 1},
        {"slot_minutes": 15},
        _with_day(2, "25:00", "26:00"),
    ],
)
def test_a_malformed_body_is_422(
    api: AppointmentsApi, clinic: Clinic, body: dict[str, Any]
) -> None:
    response = api.put_settings(clinic.owner, body)
    assert response.status_code == 422, response.text
    assert _rows(clinic.tenant_id)["slot_minutes"] is None


# --- Success -----------------------------------------------------------------------------------


def test_every_member_reads_the_defaults_until_the_owner_saves(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    response = api.client.get(URL, headers=clinic.nurse.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_default"] is True
    assert body["slot_minutes"] == 15
    assert body["hours"] == [
        {
            "weekday": day,
            "opens_at": "09:00" if day <= 5 else None,
            "closes_at": "17:00" if day <= 5 else None,
        }
        for day in range(1, 8)
    ]


def test_the_owner_saves_and_the_change_is_audited_once(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    saved = api.put_settings(clinic.owner, TUESDAY_MORNING)

    assert saved.status_code == 200, saved.text
    assert saved.json()["is_default"] is False
    assert saved.json()["bookings_outside_hours"] == 0
    read = api.client.get(URL, headers=clinic.doctor.headers).json()
    assert read["slot_minutes"] == 30
    assert read["hours"][1] == {"weekday": 2, "opens_at": "10:00", "closes_at": "11:00"}
    assert [day["opens_at"] for day in read["hours"]].count(None) == 6
    assert len(_rows(clinic.tenant_id)["hours"]) == 7, "closed days are rows, not gaps"

    # Saving the same settings again writes nothing and records nothing.
    assert api.put_settings(clinic.owner, TUESDAY_MORNING).status_code == 200
    # Changing only the slot length names only that field.
    assert (
        api.put_settings(
            clinic.owner, {**TUESDAY_MORNING, "slot_minutes": 20}
        ).status_code
        == 200
    )
    events = api.audit(clinic.tenant_id, ACTION)
    assert [(e["result"], e["metadata"]["changed_fields"]) for e in events] == [
        ("SUCCESS", ["hours", "slot_minutes"]),
        ("SUCCESS", ["slot_minutes"]),
    ]
    assert all(e["actor_id"] == clinic.owner.user_id for e in events)
    assert all(e["resource_id"] == clinic.tenant_id for e in events)


def test_the_change_and_its_event_are_one_transaction(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    real = service.audit.record

    def refuse_success(session: Any, event: Any) -> Any:
        if event.result == "SUCCESS":
            raise service.audit.AuditWriteRefused("simulated")
        return real(session, event)

    with (
        patch.object(service.audit, "record", side_effect=refuse_success),
        pytest.raises(service.audit.AuditWriteRefused),
    ):
        api.put_settings(clinic.owner, TUESDAY_MORNING)
    assert _rows(clinic.tenant_id) == {"slot_minutes": None, "hours": []}


def _local(slot: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(slot["starts_at"]).astimezone(SYDNEY)


def test_the_public_slots_follow_the_hours_and_the_slot_length(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    assert api.put_settings(clinic.owner, TUESDAY_MORNING).status_code == 200

    triage = api.slots(clinic.slug, "NURSE_TRIAGE").json()
    consult = api.slots(clinic.slug, "INITIAL_CONSULT").json()

    # Two Tuesdays fall in any 14 days from tomorrow; 10:00-11:00 on a 30-minute grid.
    for slots in (triage, consult):
        assert {_local(s).isoweekday() for s in slots} == {2}
        assert sorted({_local(s).strftime("%H:%M") for s in slots}) == [
            "10:00",
            "10:30",
        ]
        assert len(slots) == 2 * 2
    # The type still decides the length: a 30-minute consult starting 10:30 ends at closing.
    assert {
        (
            _local(s).strftime("%H:%M"),
            datetime.fromisoformat(s["ends_at"]).astimezone(SYDNEY).strftime("%H:%M"),
        )
        for s in consult
    } == {("10:00", "10:30"), ("10:30", "11:00")}

    # A 10-minute grid offers a start every 10 minutes, the last ending at or before closing.
    assert (
        api.put_settings(
            clinic.owner, {**TUESDAY_MORNING, "slot_minutes": 10}
        ).status_code
        == 200
    )
    consult = api.slots(clinic.slug, "INITIAL_CONSULT").json()
    assert sorted({_local(s).strftime("%H:%M") for s in consult}) == [
        "10:00",
        "10:10",
        "10:20",
        "10:30",
    ]


def test_a_slot_outside_the_new_hours_cannot_be_booked(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    slot = api.slots(clinic.slug, "NURSE_TRIAGE").json()[0]
    closed_that_day = week(
        {
            day: ("09:00", "17:00")
            for day in range(1, 8)
            if day != _local(slot).isoweekday()
        }
    )
    assert api.put_settings(clinic.owner, closed_that_day).status_code == 200
    refused = api.public_book(clinic.slug, slot)
    assert refused.status_code == 422
    assert code(refused) == "SLOT_NOT_OFFERED"


def test_bookings_outside_new_hours_are_counted_and_kept(
    api: AppointmentsApi, clinic: Clinic
) -> None:
    booked = api.book(
        clinic.owner,
        patient_id=clinic.patient_id,
        practitioner_id=clinic.doctor.user_id,
        starts_at=MONDAY_0900,
    )
    assert booked.status_code == 201, booked.text

    saved = api.put_settings(clinic.owner, TUESDAY_MORNING)  # Monday is now closed

    assert saved.json()["bookings_outside_hours"] == 1
    assert api.count("appointments", clinic.tenant_id) == 1
    listed = api.window(clinic.owner).json()
    assert [a["status"] for a in listed] == ["BOOKED"]
    # Reopened, nothing falls outside.
    reopened = api.put_settings(clinic.owner, week({1: ("09:00", "17:00")}))
    assert reopened.json()["bookings_outside_hours"] == 0
