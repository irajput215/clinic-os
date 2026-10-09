"""Fixtures for the patients API tests.

Both tenants are created the way production creates them — `POST /users/signup` with a
`clinic_name` — and every patient row is written through the API as that tenant. Nothing
here inserts a patient "as the owner and trusts the policy to hide it": the cross-tenant
cases prove the API refuses to hand a row to the wrong tenant.

Rows are removed at the end of each test. `patients.tenant_id` is `ON DELETE RESTRICT`, so
the patients of a tenant must go before the tenant itself does; leaving them behind would
also break `tests/tenancy`, which deletes every tenant between cases.
"""

import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine

PATIENTS_URL = f"{settings.API_V1_STR}/patients"

# Synthetic data only (`definition-of-done.md` §6: "Test data is synthetic and classified").
DEFAULT_PATIENT: dict[str, Any] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}


class TenantSession(NamedTuple):
    """One signed-up account: its tenant (None for an unattached account) and its token."""

    tenant_id: uuid.UUID | None
    user_id: uuid.UUID
    headers: dict[str, str]


class PatientsApi:
    """Small client-side helper: sign up tenants and call the patient routes as them."""

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self._tenant_ids: list[uuid.UUID] = []

    @property
    def client(self) -> TestClient:
        return self._client

    def register(self, *, clinic_name: str | None = None) -> TenantSession:
        """Register an account, optionally with an organisation, and log in."""
        email = f"patients-{uuid.uuid4()}@example.com"
        password = "correct-horse-battery-staple"
        signup: dict[str, str] = {
            "email": email,
            "password": password,
            "full_name": "Clinic Administrator",
        }
        if clinic_name is not None:
            signup["clinic_name"] = clinic_name

        created = self._client.post(f"{settings.API_V1_STR}/users/signup", json=signup)
        assert created.status_code == 200, created.text
        account = created.json()
        tenant_id = uuid.UUID(account["tenant_id"]) if account["tenant_id"] else None
        if tenant_id is not None:
            self._tenant_ids.append(tenant_id)

        token = self._client.post(
            f"{settings.API_V1_STR}/login/access-token",
            data={"username": email, "password": password},
        )
        assert token.status_code == 200, token.text
        return TenantSession(
            tenant_id=tenant_id,
            user_id=uuid.UUID(account["id"]),
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        )

    def create_raw(self, session: TenantSession, **overrides: Any) -> Response:
        return self._client.post(
            PATIENTS_URL,
            json={**DEFAULT_PATIENT, **overrides},
            headers=session.headers,
        )

    def create(self, session: TenantSession, **overrides: Any) -> dict[str, Any]:
        response = self.create_raw(session, **overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def read(self, session: TenantSession, patient_id: str) -> Response:
        return self._client.get(f"{PATIENTS_URL}/{patient_id}", headers=session.headers)

    def patch(
        self, session: TenantSession, patient_id: str, body: dict[str, Any]
    ) -> Response:
        return self._client.patch(
            f"{PATIENTS_URL}/{patient_id}", json=body, headers=session.headers
        )

    def list(
        self,
        session: TenantSession,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Response:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        return self._client.get(PATIENTS_URL, params=params, headers=session.headers)

    def search(
        self,
        session: TenantSession,
        q: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Response:
        body: dict[str, Any] = {"q": q}
        if limit is not None:
            body["limit"] = limit
        if cursor is not None:
            body["cursor"] = cursor
        return self._client.post(
            f"{PATIENTS_URL}/search", json=body, headers=session.headers
        )

    def patient_reads(self, tenant_id: uuid.UUID | None) -> list[dict[str, Any]]:
        """The tenant's `patient.read` audit events, oldest first, read as the owner."""
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT result, reason, resource_id, actor_id, metadata"
                        " FROM audit_log WHERE tenant_id = :tenant_id"
                        " AND action = 'patient.read' ORDER BY timestamp, event_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def patient_count(self, tenant_id: uuid.UUID | None) -> int:
        """Count the tenant's rows on the owner connection, which bypasses RLS.

        That is the point: the assertion is about rows that exist, not rows the policy
        would hide from the application.
        """
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT count(*) FROM patients WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            return int(result.scalar_one())

    def row(self, patient_id: str) -> dict[str, Any] | None:
        """Read one row as the owner, for "the row is unchanged" assertions."""
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT id, tenant_id, given_name, family_name, preferred_name,"
                    " date_of_birth, updated_at, deleted_at"
                    " FROM patients WHERE id = :patient_id"
                ),
                {"patient_id": uuid.UUID(patient_id)},
            )
            row = result.mappings().first()
            return None if row is None else dict(row)

    def cleanup(self) -> None:
        if not self._tenant_ids:
            return
        with engine.begin() as conn:
            for tenant_id in self._tenant_ids:
                conn.execute(
                    text("DELETE FROM patients WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
                # Signup provisions a tenant's role bundles and a `user_roles` grant, and those
                # references are ON DELETE RESTRICT, so they are removed before the account and the
                # tenant they belong to.
                conn.execute(
                    text("DELETE FROM user_roles WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
                conn.execute(
                    text("DELETE FROM role_permissions WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
                conn.execute(
                    text("DELETE FROM roles WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
                conn.execute(
                    text('DELETE FROM "user" WHERE tenant_id = :tenant_id'),
                    {"tenant_id": tenant_id},
                )
                conn.execute(
                    text("DELETE FROM tenants WHERE id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
        self._tenant_ids.clear()


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests register their own organisations; the setting is not a test fixture."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def api(client: TestClient) -> Iterator[PatientsApi]:
    helper = PatientsApi(client)
    yield helper
    helper.cleanup()
