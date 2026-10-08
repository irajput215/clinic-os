"""`GET /api/v1/dashboard/today`: the sections, their gating, isolation and audit."""

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import text

from app.core.db import engine, tenant_transaction
from app.modules.appointments import service as appointments
from app.modules.dashboard.router import read_today
from app.modules.users_roles.catalog import DASHBOARD_SECTION_PERMISSIONS
from app.modules.users_roles.policy import Actor
from tests.dashboard.conftest import API, URL, DashboardApi


def test_no_session_is_refused(dash: DashboardApi) -> None:
    assert dash.client.get(URL).status_code == 401


def test_an_inactive_identity_is_refused_not_given_an_empty_page() -> None:
    """Withholding is for a missing permission only; a refused identity refuses the whole read."""
    actor = Actor(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        is_active=False,
        permissions=frozenset(DASHBOARD_SECTION_PERMISSIONS.values()),
    )
    request = Request({"type": "http", "query_string": b"", "headers": []})
    with pytest.raises(HTTPException) as refused:
        read_today(actor=actor, request=request)
    assert refused.value.status_code == 403


def test_the_owner_sees_the_clinics_day(dash: DashboardApi) -> None:
    clinic = dash.clinic()
    owner, doctor = clinic.owner, clinic.verifier
    today = dash.today()
    covered = clinic.patient_id
    uncovered = dash.patient(clinic, "Bea", "Uncovered")

    # The schedule: two bookings today (one cancelled), and one either side that are not today's.
    late = dash.book(
        owner,
        patient_id=covered,
        practitioner_id=doctor.user_id,
        starts_at=dash.at(today, "15:00"),
    )
    early = dash.book(
        owner,
        patient_id=uncovered,
        practitioner_id=doctor.user_id,
        starts_at=dash.at(today, "09:00"),
    )
    dash.set_status(owner, early["id"], "CANCELLED")
    for other_day in (today - timedelta(days=1), today + timedelta(days=1)):
        dash.book(
            owner,
            patient_id=covered,
            practitioner_id=doctor.user_id,
            starts_at=dash.at(other_day, "12:00"),
        )

    # Approvals: one active for `covered`, expiring in 10 days; one still pending for `uncovered`.
    expiring = dash.rx.approve(clinic, **dash.expiring_in(10))
    pending = dash.tga.create(owner, uncovered, approval_reference="TGA-PENDING-0001")

    # Scripts: a covered draft and an uncovered one, both for today.
    covered_draft = dash.rx.stage(clinic, date_of_service=today.isoformat())
    uncovered_draft = dash.rx.stage(
        clinic, patient_id=str(uncovered), date_of_service=today.isoformat()
    )

    response = dash.get(owner)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["date"] == today.isoformat()
    assert body["timezone"] == "Australia/Sydney"
    assert body["withheld"] == []

    schedule = body["appointments"]
    assert [a["id"] for a in schedule["data"]] == [early["id"], late["id"]]
    assert schedule["by_status"] == {
        "BOOKED": 1,
        "CONFIRMED": 0,
        "ARRIVED": 0,
        "COMPLETED": 0,
        "CANCELLED": 1,
        "NO_SHOW": 0,
    }
    [practitioner] = dash.client.get(
        f"{API}/practitioners", headers=owner.headers
    ).json()
    assert practitioner["id"] == str(doctor.user_id)
    assert {a["practitioner_name"] for a in schedule["data"]} == {practitioner["name"]}
    assert schedule["data"][1]["patient_name"] == "Ada Synthetic"

    scripts = body["scripts"]
    assert scripts["by_state"]["DRAFT"] == 2
    assert scripts["by_state"]["QUEUED"] == 0
    assert scripts["transport_configured"] is False
    assert scripts["gate_checked"] == 2
    assert scripts["gate_refused"] == 1
    gates = {s["id"]: s["gate"] for s in scripts["actionable"]}
    assert gates[covered_draft["id"]]["matched"] is True
    assert gates[uncovered_draft["id"]]["matched"] is False
    # The pending approval is at the same grain: the gate says why it does not cover yet.
    assert (
        gates[uncovered_draft["id"]]["reason_code"]
        == "TGA_APPROVAL_PENDING_VERIFICATION"
    )
    # Newest first, as the queue lists them.
    assert [s["id"] for s in scripts["actionable"]] == [
        uncovered_draft["id"],
        covered_draft["id"],
    ]

    approvals = body["approvals"]
    assert approvals["pending_verification"] == 1
    assert approvals["expiring"] == 1
    assert approvals["expiring_within_days"] == 30
    assert [a["id"] for a in approvals["pending"]] == [pending["id"]]
    assert approvals["pending"][0]["patient_display_name"] == "Bea Uncovered"
    assert [a["id"] for a in approvals["expiring_soon"]] == [expiring["id"]]


def test_an_approval_lapsing_beyond_thirty_days_is_not_expiring(
    dash: DashboardApi,
) -> None:
    clinic = dash.clinic()
    dash.rx.approve(clinic, **dash.expiring_in(31))
    soon = dash.rx.approve(
        clinic,
        tga_category="CATEGORY_4",
        **dash.expiring_in(30),
    )
    approvals = dash.get(clinic.owner).json()["approvals"]
    assert approvals["expiring"] == 1
    assert [a["id"] for a in approvals["expiring_soon"]] == [soon["id"]]


def test_the_script_card_is_bounded_and_skips_finished_scripts(
    dash: DashboardApi,
) -> None:
    clinic = dash.clinic()
    for _ in range(9):
        dash.rx.stage(clinic)
    scripts = dash.get(clinic.owner).json()["scripts"]
    assert scripts["by_state"]["DRAFT"] == 9
    assert len(scripts["actionable"]) == 8
    # The blocked count covers every actionable script, not only the eight shown.
    assert scripts["gate_checked"] == 9
    assert scripts["gate_refused"] == 9


def test_sections_the_caller_cannot_read_are_withheld(dash: DashboardApi) -> None:
    clinic = dash.clinic()
    dash.rx.stage(clinic)
    dash.tga.create(clinic.owner, clinic.patient_id)

    # Reception reads patients and approvals, never prescriptions.
    reception = dash.rx.member(clinic, "ADMINISTRATOR")
    body = dash.get(reception).json()
    assert body["withheld"] == ["scripts"]
    assert body["scripts"] is None
    assert body["appointments"] is not None
    assert body["approvals"]["pending_verification"] == 1

    # A pharmacy account reads patients only.
    pharmacy = dash.rx.member(clinic, "PHARMACY")
    body = dash.get(pharmacy).json()
    assert body["withheld"] == ["scripts", "approvals"]
    assert body["scripts"] is None and body["approvals"] is None

    # An account holding no role sees the frame of the page and nothing in it.
    nobody = dash.rx.member(clinic, None)
    response = dash.get(nobody)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["withheld"] == ["appointments", "scripts", "approvals"]
    assert body["appointments"] is None
    assert body["scripts"] is None
    assert body["approvals"] is None


def test_the_approvals_section_is_audited_like_the_register(
    dash: DashboardApi,
) -> None:
    clinic = dash.clinic()
    tenant_id = clinic.owner.tenant_id
    assert tenant_id is not None
    dash.tga.create(clinic.owner, clinic.patient_id)
    before = len(dash.audit(tenant_id, "tga_approval.read"))

    assert dash.get(clinic.owner).status_code == 200
    events = dash.audit(tenant_id, "tga_approval.read")[before:]
    assert len(events) == 1
    [event] = events
    assert event["result"] == "SUCCESS"
    assert event["reason"] is None
    assert event["actor_id"] == clinic.owner.user_id
    assert event["payload"] == {
        "query_filters": {"state": ["PENDING"], "expiring_within_days": 30},
        "result_count": 1,
    }

    # Withheld means never read, so never audited as read.
    pharmacy = dash.rx.member(clinic, "PHARMACY")
    assert dash.get(pharmacy).status_code == 200
    assert len(dash.audit(tenant_id, "tga_approval.read")) == before + 1


def test_another_organisations_day_never_appears(dash: DashboardApi) -> None:
    ours = dash.clinic("Ours")
    theirs = dash.clinic("Theirs")
    today = dash.today()
    dash.book(
        theirs.owner,
        patient_id=theirs.patient_id,
        practitioner_id=theirs.verifier.user_id,
        starts_at=dash.at(today, "11:00"),
    )
    dash.rx.stage(theirs)
    dash.tga.create(theirs.owner, theirs.patient_id)

    # A tenant_id in the query string is ignored, and written down on the read's audit event.
    our_tenant = ours.owner.tenant_id
    assert our_tenant is not None
    response = dash.get(ours.owner, tenant_id=str(theirs.owner.tenant_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["appointments"]["data"] == []
    assert body["scripts"]["actionable"] == []
    assert sum(body["scripts"]["by_state"].values()) == 0
    assert body["approvals"]["pending_verification"] == 0
    assert body["approvals"]["pending"] == []
    [event] = dash.audit(our_tenant, "tga_approval.read")[-1:]
    assert event["reason"] == "CLIENT_TENANT_ID_IGNORED"


def test_the_clinic_day_follows_sydney_through_a_daylight_saving_change(
    dash: DashboardApi,
) -> None:
    """Daylight saving ends on Sunday 2030-04-07 in Sydney: that clinic day is 25 hours long."""
    clinic = dash.clinic()
    tenant_id = clinic.owner.tenant_id
    assert tenant_id is not None
    day = date(2030, 4, 7)
    inside = [
        dash.at(day, "00:00"),  # 00:00 AEDT (+11:00)
        dash.at(day, "23:45"),  # 23:45 AEST (+10:00)
    ]
    outside = [
        dash.at(day - timedelta(days=1), "23:45"),
        dash.at(day + timedelta(days=1), "00:00"),
    ]
    booked = {
        starts_at: dash.book(
            clinic.owner,
            patient_id=clinic.patient_id,
            practitioner_id=clinic.verifier.user_id,
            starts_at=starts_at,
        )["id"]
        for starts_at in (*inside, *outside)
    }
    with tenant_transaction(tenant_id=tenant_id) as session:
        schedule = appointments.day_schedule(session, tenant_id=tenant_id, day=day)
    assert [a.id for a in schedule.data] == [uuid.UUID(booked[s]) for s in inside]
    with engine.connect() as conn:
        hours = conn.execute(
            text(
                "SELECT extract(epoch FROM ((CAST(:d AS date) + 1)::timestamp AT TIME ZONE :z)"
                " - (CAST(:d AS date)::timestamp AT TIME ZONE :z)) / 3600"
            ),
            {"d": day, "z": "Australia/Sydney"},
        ).scalar_one()
    assert hours == 25
