"""Fixtures for the questionnaire tests (docs3 Phase 6 feature 05). Synthetic data only."""

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


class FormsApi:
    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)
        self.tenant_ids: list[uuid.UUID] = []

    def register(self) -> ActorSession:
        actor = self.rbac.register_tenant(
            clinic_name=f"Forms Clinic {uuid.uuid4().hex[:6]}"
        )
        assert actor.tenant_id is not None
        self.tenant_ids.append(actor.tenant_id)
        return actor

    def add(self, owner: ActorSession, role_code: str) -> ActorSession:
        assert owner.tenant_id is not None
        return self.rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code=role_code
        )

    def patient(self, actor: ActorSession) -> uuid.UUID:
        response = self.client.post(
            f"{API}/patients",
            json={
                "given_name": "Ada",
                "family_name": "Synthetic",
                "date_of_birth": "1990-01-01",
            },
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    def record(
        self, actor: ActorSession, patient_id: uuid.UUID, **body: Any
    ) -> Response:
        payload = {
            "instrument": "PHQ9",
            "instrument_version": "1",
            "answers": [0] * 9,
            **body,
        }
        return self.client.post(
            f"{API}/patients/{patient_id}/form-responses",
            json=payload,
            headers=actor.headers,
        )

    def history(self, actor: ActorSession, patient_id: uuid.UUID) -> Response:
        return self.client.get(
            f"{API}/patients/{patient_id}/form-responses", headers=actor.headers
        )

    def acknowledge(
        self, actor: ActorSession, flag_id: str, action_code: str = "SAFETY_PLAN_AGREED"
    ) -> Response:
        return self.client.post(
            f"{API}/safety-flags/{flag_id}/acknowledge",
            json={"action_code": action_code},
            headers=actor.headers,
        )

    def audit(self, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT result, reason, resource_id, metadata AS payload FROM audit_log"
                        ' WHERE tenant_id = :t AND action = :a ORDER BY "timestamp", event_id'
                    ),
                    {"t": tenant_id, "a": action},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def cleanup(self) -> None:
        if self.tenant_ids:
            with engine.begin() as conn:
                for table in ("safety_flags", "form_responses"):
                    conn.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                        {"ids": self.tenant_ids},
                    )
        self.rbac.cleanup()
        self.tenant_ids.clear()


class Clinic(NamedTuple):
    owner: ActorSession
    tenant_id: uuid.UUID
    patient_id: uuid.UUID


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def forms(client: TestClient, db: Session) -> Iterator[FormsApi]:
    helper = FormsApi(client, db)
    yield helper
    helper.cleanup()


@pytest.fixture
def clinic(forms: FormsApi) -> Clinic:
    owner = forms.register()
    assert owner.tenant_id is not None
    return Clinic(
        owner=owner, tenant_id=owner.tenant_id, patient_id=forms.patient(owner)
    )


def code(response: Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None
