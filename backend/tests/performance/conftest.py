"""Fixtures for the round-trip budget tests (`docs/reference/performance.md` §4).

Each clinic is registered the way production registers one (`POST /users/signup`), and every
request goes through the real app, so the count is what a request in production costs.

Two clinics:

- `clinic`: freshly registered and empty, the floor of every count.
- `seeded`: a working day's worth of rows, written through the API the way a clinic writes them, so
  a per-row query (an N+1) shows up as extra round trips instead of hiding behind an empty list.
"""

import uuid
from collections.abc import Iterator
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.core.rate_limit import limiter
from app.core.server_timing import SERVER_TIMING_HEADER
from tests.dashboard.conftest import DashboardApi
from tests.patients.conftest import PatientsApi, TenantSession
from tests.prescriptions.conftest import Clinic
from tests.utils.rbac import ActorSession

API = settings.API_V1_STR

#: The seeded clinic's size: the shape of a small practice's day.
SEEDED_PATIENTS = 25
SEEDED_APPOINTMENTS_TODAY = 15
SEEDED_APPROVALS = 10
SEEDED_SCRIPTS = 10
SEEDED_NOTES = 3


def round_trips(response: Response) -> int:
    """The database round trips the app spent on this response (its `Server-Timing` `db-rt`)."""
    for metric in response.headers[SERVER_TIMING_HEADER].split(", "):
        name, _, value = metric.partition(";")
        if name == "db-rt":
            return int(value.split("=", 1)[1].strip('"'))
    raise AssertionError(f"no db-rt in {response.headers[SERVER_TIMING_HEADER]!r}")


@pytest.fixture
def clinic(client: TestClient) -> Iterator[TenantSession]:
    """A freshly registered clinic and its owner's session; its rows are removed afterwards."""
    api = PatientsApi(client)
    try:
        yield api.register(clinic_name="Round Trip Clinic")
    finally:
        api.cleanup()


class SeededClinic(NamedTuple):
    """A clinic with three staff and a day of work. `patient_id` has a full record on every tab."""

    owner: ActorSession
    doctor: ActorSession
    nurse: ActorSession
    patient_id: uuid.UUID
    patient_ids: list[uuid.UUID]


def _seed(dash: DashboardApi) -> SeededClinic:
    """Three staff, 25 patients, 15 bookings today, 10 approvals in mixed states, 10 scripts, notes.

    Every row is written through the API. The rate limiter is cleared between batches: it bounds a
    session's writes per minute, and seeding is one session writing a day's work at once.
    """
    base = dash.clinic("Round Trip Seeded Clinic")
    owner, doctor = base.owner, base.verifier
    nurse = dash.rx.member(base, "NURSE")
    patient_ids = [base.patient_id] + [
        dash.patient(base, f"Given{index:02d}", f"Family{index:02d}")
        for index in range(1, SEEDED_PATIENTS)
    ]
    limiter.clear()

    today = dash.today()
    for index in range(SEEDED_APPOINTMENTS_TODAY):
        practitioner, kind = (
            (doctor, "FOLLOW_UP") if index % 2 == 0 else (nurse, "NURSE_TRIAGE")
        )
        booked = dash.client.post(
            f"{API}/appointments",
            json={
                "patient_id": str(patient_ids[index]),
                "practitioner_id": str(practitioner.user_id),
                "type": kind,
                "starts_at": dash.at(today, f"{7 + index // 2:02d}:30"),
            },
            headers=owner.headers,
        )
        assert booked.status_code == 201, booked.text
    limiter.clear()

    # Approvals: active (each expiring within the Today window), pending verification, and revoked,
    # spread over five patients; the record patient holds an active and a revoked one.
    for index in range(SEEDED_APPROVALS):
        clinic = Clinic(owner, doctor, patient_ids[index % 5])
        category = f"CATEGORY_{index // 5 + 3}"
        if index % 3 == 0:
            dash.rx.approve(
                clinic, tga_category=category, **dash.expiring_in(index + 5)
            )
        elif index % 3 == 1:
            dash.tga.create(
                owner,
                clinic.patient_id,
                tga_category=category,
                dosage_form="ORAL_CAPSULE",
                approval_reference=f"TGA-PEND-{index:04d}",
            )
        else:
            pending = dash.tga.create(
                owner,
                clinic.patient_id,
                tga_category=category,
                dosage_form="ORAL_SPRAY",
                approval_reference=f"TGA-REVK-{index:04d}",
            )
            assert dash.tga.revoke(owner, pending["id"]).status_code == 200
    limiter.clear()

    # Scripts: drafts across five patients, the gate covering some and refusing others; the record
    # patient's are signed (its active approval covers them), so the queue holds two states.
    for index in range(SEEDED_SCRIPTS):
        script = dash.rx.stage(
            Clinic(owner, doctor, patient_ids[index % 5]),
            date_of_service=today.isoformat(),
        )
        if index % 5 == 0:
            signed = dash.rx.sign_raw(owner, script["id"])
            assert signed.status_code == 200, signed.text
    limiter.clear()

    for _ in range(SEEDED_NOTES):
        created = dash.client.post(
            f"{API}/clinical-records",
            json={
                "patient_id": str(base.patient_id),
                "body": "Synthetic consult note. Review in two weeks.",
            },
            headers=doctor.headers,
        )
        assert created.status_code == 201, created.text
    limiter.clear()

    return SeededClinic(owner, doctor, nurse, base.patient_id, patient_ids)


@pytest.fixture(scope="module")
def seeded(client: TestClient, db: Session) -> Iterator[SeededClinic]:
    """One seeded clinic for the module; its rows are removed afterwards (children first)."""
    dash = DashboardApi(client, db)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "USERS_OPEN_REGISTRATION", True)
        try:
            yield _seed(dash)
        finally:
            # Clinical versions are append-only for every role and only `TRUNCATE` removes them
            # (`tests/clinical_records/conftest.py`); no other module's rows live in these tables.
            with engine.begin() as conn:
                conn.execute(
                    text("TRUNCATE clinical_records, clinical_record_versions")
                )
            dash.cleanup()
