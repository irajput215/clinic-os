"""Fixtures for the prescriptions module (FEAT-10 gate, FEAT-11 prescribing, the outbox).

Organisations are created through the real signup route; approvals are recorded and verified through
the TGA API by two different clinicians (the four-eyes rule); every prescription action goes through
the HTTP API with a real step-up grant. Nothing here inserts a "signed" row by hand, except the
database-control tests, which provoke the triggers on purpose.

Synthetic data only. `CATEGORY_3` / `ORAL_OIL` are token *shapes*, not a clinical vocabulary.
"""

import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from tests.tga.conftest import TgaApi
from tests.utils.rbac import ActorSession

API = settings.API_V1_STR
URL = f"{API}/prescriptions"

DEFAULT_DRAFT: dict[str, Any] = {
    "medicine_name": "Synthetic Oil 10:10",
    "tga_category": "CATEGORY_3",
    "dosage_form": "ORAL_OIL",
    "dose_instruction": "0.5 mL nocte, titrate weekly",
    "quantity": "1",
    "repeats": 2,
    "triage_outcome": "Eligible - chronic pain",
    "conventional_therapy": "Paracetamol and NSAIDs for 6 months",
    "date_of_service": "2026-06-01",
}


class Clinic(NamedTuple):
    owner: ActorSession
    verifier: ActorSession
    patient_id: uuid.UUID


class RxApi:
    """Drive the prescriptions routes the way a client does."""

    def __init__(self, client: TestClient, tga: TgaApi) -> None:
        self.client = client
        self.tga = tga
        self._tenants: list[uuid.UUID] = []

    # -- setup ---------------------------------------------------------------------------------

    def clinic(self, name: str = "Rx Clinic") -> Clinic:
        owner = self.tga.register(clinic_name=name)
        assert owner.tenant_id is not None
        self._tenants.append(owner.tenant_id)
        verifier = self.tga.second_clinician(owner=owner, role_code="DOCTOR")
        return Clinic(owner, verifier, self.tga.create_patient(owner))

    def member(self, clinic: Clinic, role_code: str | None) -> ActorSession:
        assert clinic.owner.tenant_id is not None
        return self.tga.rbac.add_actor(
            tenant_id=clinic.owner.tenant_id,
            granted_by=clinic.owner.user_id,
            role_code=role_code,
        )

    def approve(
        self,
        clinic: Clinic,
        *,
        valid_from: str = "2026-01-01",
        valid_to: str = "2027-01-01",
        reference: str | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        """An `ACTIVE` approval: created by the owner, verified by the second clinician."""
        approval = self.tga.create(
            clinic.owner,
            clinic.patient_id,
            valid_from=valid_from,
            valid_to=valid_to,
            approval_reference=reference or f"TGA-{uuid.uuid4().hex[:10].upper()}",
            **overrides,
        )
        verified = self.tga.activate(clinic.owner, approval, verifier=clinic.verifier)
        assert verified.status_code == 200, verified.text
        return approval

    # -- routes --------------------------------------------------------------------------------

    def stage_raw(
        self, actor: ActorSession, clinic: Clinic, **overrides: Any
    ) -> Response:
        body = {
            **DEFAULT_DRAFT,
            "patient_id": str(clinic.patient_id),
            "prescriber_id": str(clinic.owner.user_id),
            **overrides,
        }
        return self.client.post(URL, json=body, headers=actor.headers)

    def stage(
        self, clinic: Clinic, actor: ActorSession | None = None, **overrides: Any
    ) -> dict[str, Any]:
        response = self.stage_raw(actor or clinic.owner, clinic, **overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def step_up_raw(
        self,
        actor: ActorSession,
        resource_id: str,
        operation: str = "prescription.sign",
        password: str | None = None,
    ) -> Response:
        return self.client.post(
            f"{API}/auth/step-up",
            json={
                "password": actor.password if password is None else password,
                "operation": operation,
                "resource_id": resource_id,
            },
            headers=actor.headers,
        )

    def step_up(
        self,
        actor: ActorSession,
        resource_id: str,
        operation: str = "prescription.sign",
    ) -> str:
        response = self.step_up_raw(actor, resource_id, operation)
        assert response.status_code == 201, response.text
        return str(response.json()["step_up_token"])

    def sign_raw(
        self, actor: ActorSession, prescription_id: str, token: str | None = None
    ) -> Response:
        return self.client.post(
            f"{URL}/{prescription_id}/sign",
            json={"step_up_token": token or self.step_up(actor, prescription_id)},
            headers=actor.headers,
        )

    def dispatch_raw(
        self,
        actor: ActorSession,
        prescription_id: str,
        *,
        key: str | None = "intent-1",
        token: str | None = None,
    ) -> Response:
        headers = dict(actor.headers)
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.client.post(
            f"{URL}/{prescription_id}/dispatch",
            json={
                "step_up_token": token
                or self.step_up(actor, prescription_id, "prescription.dispatch")
            },
            headers=headers,
        )

    def list(self, actor: ActorSession, **params: Any) -> Response:
        return self.client.get(URL, params=params, headers=actor.headers)

    # -- direct reads (owner connection) ------------------------------------------------------

    def row(self, prescription_id: str) -> dict[str, Any]:
        with engine.connect() as conn:
            found = (
                conn.execute(
                    text("SELECT * FROM prescriptions WHERE id = :id"),
                    {"id": uuid.UUID(prescription_id)},
                )
                .mappings()
                .one()
            )
            return dict(found)

    def attempts(self, prescription_id: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM dispatch_attempts WHERE prescription_id = :id ORDER BY attempt_seq"
                ),
                {"id": uuid.UUID(prescription_id)},
            ).mappings()
            return [dict(row) for row in rows]

    def events(self, prescription_id: str) -> list[tuple[str | None, str]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT from_state, to_state FROM prescription_events"
                    " WHERE prescription_id = :id ORDER BY occurred_at, id"
                ),
                {"id": uuid.UUID(prescription_id)},
            ).all()
            return [(row[0], row[1]) for row in rows]

    def audit(self, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT action, result, reason, resource_id, actor_id, metadata AS payload"
                    " FROM audit_log WHERE tenant_id = :tenant_id AND action = :action"
                    ' ORDER BY "timestamp", event_id'
                ),
                {"tenant_id": tenant_id, "action": action},
            ).mappings()
            return [dict(row) for row in rows]

    def cleanup(self) -> None:
        with engine.begin() as conn:
            for tenant_id in self._tenants:
                for table in (
                    "prescription_events",
                    "dispatch_attempts",
                    "prescriptions",
                    "step_up_grants",
                ):
                    conn.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                        {"tenant_id": tenant_id},
                    )
        self._tenants.clear()
        self.tga.cleanup()


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def rx(client: TestClient, db: Session) -> Iterator[RxApi]:
    helper = RxApi(client, TgaApi(client, db))
    yield helper
    helper.cleanup()


@pytest.fixture
def clinic(rx: RxApi) -> Clinic:
    return rx.clinic()


def code(response: Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None
