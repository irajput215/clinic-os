"""Fixtures for the dashboard module (`GET /api/v1/dashboard/today`).

The data is created the way a clinic creates it: organisations through signup, approvals recorded and
verified by two clinicians through the TGA API, scripts staged through the prescriptions API and
bookings made through the appointments API. Times are the clinic's (Australia/Sydney), computed from
the database clock the server reads. Synthetic data only.
"""

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from tests.prescriptions.conftest import Clinic, RxApi
from tests.tga.conftest import TgaApi
from tests.utils.rbac import ActorSession

API = settings.API_V1_STR
URL = f"{API}/dashboard/today"
ZONE = "Australia/Sydney"


class DashboardApi:
    """The prescriptions helper (which carries the TGA one), plus bookings and the clinic clock."""

    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rx = RxApi(client, TgaApi(client, db))
        self.tga = self.rx.tga

    def today(self) -> date:
        with engine.connect() as conn:
            value = conn.execute(
                text("SELECT (now() AT TIME ZONE :zone)::date"), {"zone": ZONE}
            ).scalar_one()
        assert isinstance(value, date)
        return value

    def at(self, day: date, hhmm: str) -> str:
        """`hhmm` on the clinic day `day`, as an ISO instant with Sydney's offset that day."""
        with engine.connect() as conn:
            value = conn.execute(
                text(
                    "SELECT to_char((CAST(:day AS date) + CAST(:t AS time))::timestamp"
                    " AT TIME ZONE :zone AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
                ),
                {"day": day, "t": hhmm, "zone": ZONE},
            ).scalar_one()
        return str(value)

    def clinic(self, name: str = "Today Clinic") -> Clinic:
        return self.rx.clinic(name)

    def patient(self, clinic: Clinic, given: str, family: str) -> uuid.UUID:
        return self.tga.create_patient(
            clinic.owner, given_name=given, family_name=family
        )

    def book(
        self,
        actor: ActorSession,
        *,
        patient_id: uuid.UUID,
        practitioner_id: uuid.UUID,
        starts_at: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"{API}/appointments",
            json={
                "patient_id": str(patient_id),
                "practitioner_id": str(practitioner_id),
                "type": "FOLLOW_UP",
                "starts_at": starts_at,
            },
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    def set_status(self, actor: ActorSession, appointment_id: str, status: str) -> None:
        response = self.client.post(
            f"{API}/appointments/{appointment_id}/status",
            json={"status": status},
            headers=actor.headers,
        )
        assert response.status_code == 200, response.text

    def expiring_in(self, days: int) -> dict[str, str]:
        """An approval window whose last covered day is `days` from today (half-open `[)`)."""
        today = self.today()
        return {
            "valid_from": (today - timedelta(days=30)).isoformat(),
            "valid_to": (today + timedelta(days=days + 1)).isoformat(),
        }

    def get(self, actor: ActorSession, **params: Any) -> Response:
        return self.client.get(URL, params=params, headers=actor.headers)

    def audit(self, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        return self.rx.audit(tenant_id, action)

    def cleanup(self) -> None:
        with engine.begin() as conn:
            for tenant_id in self.rx._tenants:
                conn.execute(
                    text("DELETE FROM appointments WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
        self.rx.cleanup()


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def dash(client: TestClient, db: Session) -> Iterator[DashboardApi]:
    helper = DashboardApi(client, db)
    yield helper
    helper.cleanup()
