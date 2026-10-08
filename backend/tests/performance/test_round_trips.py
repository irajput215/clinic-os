"""Database round trips per request, pinned so they cannot creep back (`performance.md` §4).

Production pays the full app-to-database latency once per round trip (about 216 ms on 2026-10-08,
`docs/reference/performance.md` §3), so a round trip added to a hot request is a regression a user
feels, even though no test of behaviour would notice it. The counts come from the app's own
`Server-Timing` header, which is measured inside the driver.

The budget for a typical read is three: the request's prelude (the account, its organisation's
status and its grants, in one flight), the route's first statement (which carries the transaction's
`BEGIN` and tenant context), and `COMMIT`. Every hot screen is pinned twice:

- on a **seeded** clinic (three staff, 25 patients, 15 bookings today, 10 approvals in mixed states,
  10 scripts, consult notes; `tests/performance/conftest.py`), so a per-row query (an N+1) shows up
  as extra round trips instead of hiding behind an empty list;
- on an **empty** clinic, the floor: a lookup that has nothing to look up costs nothing.

Each budget's breakdown is written beside it. "Prelude" is the session prelude, "BEGIN+" the
transaction's first flight (its `BEGIN` and tenant context ride with it), "audit" the two trips of
an audited read (the chain lock with its head, then the insert, `app.modules.audit.service.record`).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.patients.conftest import TenantSession
from tests.performance.conftest import (
    SEEDED_APPOINTMENTS_TODAY,
    SEEDED_NOTES,
    SEEDED_PATIENTS,
    SEEDED_SCRIPTS,
    SeededClinic,
    round_trips,
)

API = settings.API_V1_STR


def _week() -> str:
    start = datetime.now(UTC).replace(microsecond=0) - timedelta(days=1)
    end = start + timedelta(days=7)
    return f"from={start.isoformat()}&to={end.isoformat()}".replace("+", "%2B")


@dataclass(frozen=True)
class Budget:
    """One hot read: its round trips on a seeded and on an empty clinic, and why."""

    name: str
    path: str  # `{patient}` is the clinic's record patient
    seeded: int
    empty: int
    why: str
    #: On the seeded clinic: proof the response carried the rows an N+1 would have multiplied.
    seeded_rows: Callable[[Any], int] = lambda body: 1
    method: str = "GET"
    body: dict[str, Any] | None = None


def _data(body: Any) -> int:  # noqa: ANN401 - a JSON body
    return len(body["data"])


BUDGETS = [
    Budget(
        "today",
        "/dashboard/today",
        seeded=7,
        empty=6,
        why="prelude, BEGIN+ the clinic day (date and bounds in one statement), every section's"
        " rows in one flight (bookings; script counts and actionable scripts; approval totals,"
        " pending and expiring), every lookup in the next (patient and staff names, dispatch"
        " attempts, the gate's approvals; none on an empty clinic), audit (tga_approval.read),"
        " COMMIT",
        seeded_rows=lambda body: (
            len(body["appointments"]["data"])
            + len(body["scripts"]["actionable"])
            + len(body["approvals"]["pending"])
        ),
    ),
    Budget(
        "patients list",
        "/patients",
        seeded=5,
        empty=5,
        why="prelude, BEGIN+ the page with its total, audit (patient.read), COMMIT",
        seeded_rows=lambda body: body["count"],
    ),
    Budget(
        "patients search",
        "/patients/search",
        method="POST",
        body={"q": "fam"},
        seeded=5,
        empty=5,
        why="prelude, BEGIN+ the page with its total, audit (patient.read), COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "patient record",
        "/patients/{patient}",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ the patient, COMMIT",
    ),
    Budget(
        "record: consult notes",
        "/patients/{patient}/clinical-records",
        seeded=5,
        empty=5,
        why="prelude, BEGIN+ the patient, the total, the page and its current versions in one"
        " flight, audit (clinical_record.read), COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "record: appointments",
        "/patients/{patient}/appointments",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ the patient and its bookings in one flight, COMMIT",
        seeded_rows=len,
    ),
    Budget(
        "record: approvals",
        "/patients/{patient}/tga-approvals",
        seeded=5,
        empty=5,
        why="prelude, BEGIN+ the patient and the page in one flight, audit (tga_approval.read),"
        " COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "record: scripts",
        "/prescriptions?patient_id={patient}",
        seeded=4,
        empty=3,
        why="prelude, BEGIN+ the page, its names, dispatch attempts and gate answers in one flight"
        " (none on an empty page), COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "record: activity",
        "/audit/events?resource_id={patient}&limit=50",
        seeded=5,
        empty=5,
        why="prelude, BEGIN+ the page, audit (the read of the trail is itself audited), COMMIT",
    ),
    Budget(
        "approvals register",
        "/tga-approvals",
        seeded=7,
        empty=6,
        why="prelude, BEGIN+ the service date, the page and the totals (one statement) in one"
        " flight, audit (tga_approval.read), the patients' names (none on an empty page), COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "scripts queue",
        "/prescriptions",
        seeded=4,
        empty=3,
        why="prelude, BEGIN+ the page, its names, dispatch attempts and gate answers in one flight"
        " (none on an empty page), COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "calendar week",
        "/appointments?{week}",
        seeded=4,
        empty=3,
        why="prelude, BEGIN+ the bookings, the patients' names (none on an empty week), COMMIT",
        seeded_rows=len,
    ),
    Budget(
        "staff",
        "/users/staff",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ the page, its total and every account's roles in one statement, COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "roles matrix",
        "/roles",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ every role joined to its grants, COMMIT",
        seeded_rows=_data,
    ),
    Budget(
        "practitioners",
        "/practitioners",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ the active accounts joined to their practitioner roles, COMMIT",
        seeded_rows=len,
    ),
    Budget(
        "prescribers",
        "/prescriptions/prescribers",
        seeded=3,
        empty=3,
        why="prelude, BEGIN+ the active accounts joined through their grants, COMMIT",
        seeded_rows=_data,
    ),
]


def _measure(
    client: TestClient, headers: dict[str, str], budget: Budget, patient_id: uuid.UUID
) -> tuple[int, Any]:
    path = budget.path.format(patient=patient_id, week=_week())

    def send() -> Any:  # noqa: ANN401 - the client's response
        return client.request(
            budget.method, f"{API}{path}", json=budget.body, headers=headers
        )

    # Once first, so the counted request finds the pool warm.
    send()
    response = send()
    assert response.status_code == 200, response.text
    return round_trips(response), response.json()


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.name)
def test_a_seeded_clinic_stays_within_budget(
    client: TestClient, seeded: SeededClinic, budget: Budget
) -> None:
    spent, body = _measure(client, seeded.owner.headers, budget, seeded.patient_id)
    assert budget.seeded_rows(body) > 0, "the seed did not reach this read"
    assert spent == budget.seeded, budget.why


@pytest.mark.parametrize("budget", BUDGETS, ids=lambda budget: budget.name)
def test_an_empty_clinic_stays_within_budget(
    client: TestClient, clinic: TenantSession, budget: Budget
) -> None:
    created = client.post(
        f"{API}/patients",
        json={
            "given_name": "Ada",
            "family_name": "Floor",
            "date_of_birth": "1990-01-01",
        },
        headers=clinic.headers,
    )
    assert created.status_code == 201, created.text
    spent, _ = _measure(client, clinic.headers, budget, uuid.UUID(created.json()["id"]))
    assert spent == budget.empty, budget.why


def test_the_seeded_reads_return_the_whole_seed(
    client: TestClient, seeded: SeededClinic
) -> None:
    """The budgets above were met on the full seed, not on a page the seed did not fill."""
    headers = seeded.owner.headers
    today = client.get(f"{API}/dashboard/today", headers=headers).json()
    assert len(today["appointments"]["data"]) == SEEDED_APPOINTMENTS_TODAY
    assert sum(today["scripts"]["by_state"].values()) == SEEDED_SCRIPTS
    assert today["scripts"]["gate_checked"] == SEEDED_SCRIPTS
    patients = client.get(f"{API}/patients", headers=headers).json()
    assert patients["count"] == SEEDED_PATIENTS
    scripts = client.get(f"{API}/prescriptions", headers=headers).json()
    assert len(scripts["data"]) == SEEDED_SCRIPTS
    notes = client.get(
        f"{API}/patients/{seeded.patient_id}/clinical-records", headers=headers
    ).json()
    assert len(notes["data"]) == SEEDED_NOTES


def test_the_readiness_probe_is_one_round_trip(client: TestClient) -> None:
    client.get(f"{API}/health/ready/")
    assert round_trips(client.get(f"{API}/health/ready/")) == 1


@pytest.mark.parametrize("path", ["/users/me", "/users/me/permissions"])
def test_the_session_prelude_is_one_round_trip(
    client: TestClient, clinic: TenantSession, path: str
) -> None:
    """Account, organisation status, tenant context and grants: one flight, nothing else."""
    response = client.get(f"{API}{path}", headers=clinic.headers)
    response = client.get(f"{API}{path}", headers=clinic.headers)
    assert response.status_code == 200, response.text
    assert round_trips(response) == 1
