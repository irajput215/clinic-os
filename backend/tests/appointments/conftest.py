"""Fixtures for the appointments module (calendar and public booking).

Organisations are created through the real signup route and staff are added holding exactly one
role, as `tests/utils/rbac.py` does for every module. Bookings go through the API; the constraint and
RLS cases use raw SQL on purpose (the owner connection to ask "does this row exist", `SET LOCAL ROLE
clinos_app` to provoke the policy). Synthetic data only.
"""

import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR

# A Monday, far enough ahead that no clock moves it into the past. 09:00 Sydney (AEDT, +11:00).
MONDAY_0900 = "2030-03-04T09:00:00+11:00"
MONDAY_0915 = "2030-03-04T09:15:00+11:00"
MONDAY_0905 = "2030-03-04T09:05:00+11:00"

PATIENT: dict[str, Any] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}


class Clinic(NamedTuple):
    slug: str
    tenant_id: uuid.UUID
    owner: ActorSession
    doctor: ActorSession
    nurse: ActorSession
    patient_id: uuid.UUID


class AppointmentsApi:
    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)
        self._tenant_ids: list[uuid.UUID] = []

    # -- setup ----------------------------------------------------------------------------------

    def clinic(self, *, name: str | None = None) -> Clinic:
        clinic_name = name or f"Synthetic Clinic {uuid.uuid4().hex[:8]}"
        owner = self.rbac.register_tenant(clinic_name=clinic_name)
        assert owner.tenant_id is not None
        self._tenant_ids.append(owner.tenant_id)
        doctor = self.staff(owner, "DOCTOR", full_name="Dr Wren Example")
        nurse = self.staff(owner, "NURSE", full_name="Kit Example, RN")
        patient = self.client.post(
            f"{API}/patients", json=PATIENT, headers=owner.headers
        )
        assert patient.status_code == 201, patient.text
        with engine.connect() as conn:
            slug = conn.execute(
                text("SELECT slug FROM tenants WHERE id = :id"), {"id": owner.tenant_id}
            ).scalar_one()
        return Clinic(
            slug=str(slug),
            tenant_id=owner.tenant_id,
            owner=owner,
            doctor=doctor,
            nurse=nurse,
            patient_id=uuid.UUID(patient.json()["id"]),
        )

    def staff(
        self,
        owner: ActorSession,
        role_code: str | None,
        *,
        full_name: str | None = None,
    ) -> ActorSession:
        assert owner.tenant_id is not None
        actor = self.rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code=role_code
        )
        if full_name is not None:
            with engine.begin() as conn:
                conn.execute(
                    text('UPDATE "user" SET full_name = :name WHERE id = :id'),
                    {"name": full_name, "id": actor.user_id},
                )
        return actor

    # -- staff routes ---------------------------------------------------------------------------

    def book(
        self,
        actor: ActorSession,
        *,
        patient_id: uuid.UUID,
        practitioner_id: uuid.UUID,
        type: str = "FOLLOW_UP",
        starts_at: str = MONDAY_0900,
        **extra: Any,
    ) -> Response:
        return self.client.post(
            f"{API}/appointments",
            json={
                "patient_id": str(patient_id),
                "practitioner_id": str(practitioner_id),
                "type": type,
                "starts_at": starts_at,
                **extra,
            },
            headers=actor.headers,
        )

    def set_status(
        self, actor: ActorSession, appointment_id: str, status: str
    ) -> Response:
        return self.client.post(
            f"{API}/appointments/{appointment_id}/status",
            json={"status": status},
            headers=actor.headers,
        )

    def window(self, actor: ActorSession, **params: Any) -> Response:
        query = {
            "from": "2030-03-04T00:00:00+11:00",
            "to": "2030-03-05T00:00:00+11:00",
            **params,
        }
        return self.client.get(
            f"{API}/appointments", params=query, headers=actor.headers
        )

    # -- public routes --------------------------------------------------------------------------

    def slots(self, slug: str, type: str = "NURSE_TRIAGE") -> Response:
        return self.client.get(f"{API}/public/{slug}/slots", params={"type": type})

    def public_book(
        self, slug: str, slot: dict[str, Any], **overrides: Any
    ) -> Response:
        body = {
            "type": "NURSE_TRIAGE",
            "practitioner_id": slot["practitioner_id"],
            "starts_at": slot["starts_at"],
            "given_name": "Nora",
            "family_name": "Quinn",
            "date_of_birth": "1990-03-21",
            "email": "nora.quinn@example.com",
            "phone": "0412 555 019",
            "consent": True,
            **overrides,
        }
        return self.client.post(f"{API}/public/{slug}/bookings", json=body)

    # -- owner-connection reads -----------------------------------------------------------------

    def audit(self, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT action, result, reason, resource_id, actor_id, actor_role,"
                    " source_ip, metadata FROM audit_log"
                    " WHERE tenant_id = :tenant_id AND action = :action"
                    ' ORDER BY "timestamp", event_id'
                ),
                {"tenant_id": tenant_id, "action": action},
            ).mappings()
            return [dict(row) for row in rows]

    def count(self, table: str, tenant_id: uuid.UUID) -> int:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                    {"t": tenant_id},
                ).scalar_one()
            )

    def cleanup(self) -> None:
        with engine.begin() as conn:
            for tenant_id in self._tenant_ids:
                for table in ("appointments", "appointment_settings"):
                    conn.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                        {"t": tenant_id},
                    )
        self.rbac.cleanup()
        self._tenant_ids.clear()


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def api(client: TestClient, db: Session) -> Iterator[AppointmentsApi]:
    helper = AppointmentsApi(client, db)
    yield helper
    helper.cleanup()


@pytest.fixture
def clinic(api: AppointmentsApi) -> Clinic:
    return api.clinic()


def code(response: Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None
