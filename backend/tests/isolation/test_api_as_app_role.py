"""The API, driven end to end with the app connected as `clinos_app`.

Every other API test connects as the `postgres` superuser, which bypasses RLS and every grant, so a
query asking for a column the application role may not read passes the whole suite and fails only in
a deployment that connects as `clinos_app`. Two did exactly that: `GET /tenants/current` (unreadable
`tenants.created_at`) and the public booking page (an ORM read of every `tenants` column). This module
makes every pooled connection `SET ROLE clinos_app` at checkout, so the same mismatch fails here.

The role is set per connection with `SET ROLE` (not `SET LOCAL`, which would need a transaction the
app has not opened yet) and reset at checkin, so no other test inherits it.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.config import settings
from app.core.db import engine
from app.main import app
from tests.utils.signup import sign_up

API = settings.API_V1_STR
PASSWORD = "app-role-check-9f2c"


def _run_outside_a_transaction(dbapi_connection: Any, statement: str) -> None:  # noqa: ANN401
    autocommit = dbapi_connection.autocommit
    dbapi_connection.autocommit = True
    try:
        dbapi_connection.execute(statement)
    finally:
        dbapi_connection.autocommit = autocommit


def _become_app_role(dbapi_connection: Any, *_: Any) -> None:  # noqa: ANN401
    _run_outside_a_transaction(dbapi_connection, "SET ROLE clinos_app")


def _reset_role(dbapi_connection: Any, *_: Any) -> None:  # noqa: ANN401
    if not dbapi_connection.closed:
        _run_outside_a_transaction(dbapi_connection, "RESET ROLE")


# Child tables first: every reference to a tenant, its accounts and its patients is RESTRICT.
_CLEANUP_ORDER = (
    "appointment_notifications",
    "patient_consents",
    "intake_applications",
    "appointments",
    "appointment_hours",
    "appointment_settings",
    "care_relationships",
    "patient_alerts",
    "patient_emergency_contacts",
    "patients",
    "pharmacies",
    "staff_invitations",
    "user_roles",
    "role_permissions",
    "roles",
)


@pytest.fixture(scope="module")
def as_app_role() -> Iterator[TestClient]:
    event.listen(engine, "checkout", _become_app_role)
    event.listen(engine, "checkin", _reset_role)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        event.remove(engine, "checkout", _become_app_role)
        event.remove(engine, "checkin", _reset_role)
        # Back as the superuser (every connection reset its role at checkin): remove the clinic
        # this module registered, so later tests that clear `tenants` find nothing of it.
        with engine.begin() as connection:
            tenant_ids = [
                row[0]
                for row in connection.execute(
                    text("SELECT id FROM tenants WHERE slug LIKE 'app-role-clinic-%'")
                )
            ]
            for tenant_id in tenant_ids:
                for table in _CLEANUP_ORDER:
                    connection.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                        {"t": tenant_id},
                    )
                connection.execute(
                    text('DELETE FROM "user" WHERE tenant_id = :t'), {"t": tenant_id}
                )
                connection.execute(
                    text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id}
                )


@pytest.fixture(scope="module")
def owner(as_app_role: TestClient) -> dict[str, str]:
    """A clinic registered through the public signup and verify routes, all as `clinos_app`.

    `sign_up` captures the verification email instead of sending it (no SMTP socket is opened) and
    follows its link, exactly as a person would.
    """
    signed_up = sign_up(
        as_app_role,
        {
            "email": f"app-role-{uuid.uuid4().hex[:8]}@example.com",
            "password": PASSWORD,
            "full_name": "App Role Owner",
            "clinic_name": f"App Role Clinic {uuid.uuid4().hex[:6]}",
        },
    )
    return signed_up.headers


def _week() -> str:
    start = datetime.now(UTC).replace(microsecond=0)
    end = start + timedelta(days=7)
    return f"from={start.isoformat()}&to={end.isoformat()}".replace("+", "%2B")


@pytest.mark.parametrize(
    "path",
    [
        "/users/me",
        "/users/me/permissions",
        "/tenants/current",
        "/tenants/current/profile",
        "/dashboard/today",
        "/roles",
        "/permissions",
        "/users/staff",
        "/patients",
        "/practitioners",
        "/appointment-settings",
        "/tga-approvals",
        "/prescriptions",
        f"/appointments?{_week()}",
    ],
)
def test_signed_in_reads_work_as_the_app_role(
    as_app_role: TestClient, owner: dict[str, str], path: str
) -> None:
    response = as_app_role.get(f"{API}{path}", headers=owner)
    assert response.status_code == 200, response.text


def test_patient_lifecycle_works_as_the_app_role(
    as_app_role: TestClient, owner: dict[str, str]
) -> None:
    created = as_app_role.post(
        f"{API}/patients",
        headers=owner,
        json={
            "given_name": "Ada",
            "family_name": "Role",
            "date_of_birth": "1980-02-03",
            "phone": "0412345678",
        },
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]
    for path in (
        f"/patients/{patient_id}",
        f"/patients/{patient_id}/appointments",
        f"/patients/{patient_id}/care-relationships",
        f"/patients/{patient_id}/clinical-records",
        f"/patients/{patient_id}/tga-approvals",
    ):
        response = as_app_role.get(f"{API}{path}", headers=owner)
        assert response.status_code == 200, f"{path}: {response.text}"
    updated = as_app_role.patch(
        f"{API}/patients/{patient_id}", headers=owner, json={"phone": "0412000000"}
    )
    assert updated.status_code == 200, updated.text
    found = as_app_role.post(
        f"{API}/patients/search", headers=owner, json={"q": "Role"}
    )
    assert found.status_code == 200, found.text


def test_account_updates_work_as_the_app_role(
    as_app_role: TestClient, owner: dict[str, str]
) -> None:
    """The app role may update only `email`, `full_name`, `hashed_password` and `is_active`."""
    renamed = as_app_role.patch(
        f"{API}/users/me", headers=owner, json={"full_name": "Renamed Owner"}
    )
    assert renamed.status_code == 200, renamed.text
    changed = as_app_role.patch(
        f"{API}/users/me/password",
        headers=owner,
        json={"current_password": PASSWORD, "new_password": PASSWORD + "-2"},
    )
    assert changed.status_code == 200, changed.text


def test_public_booking_page_works_as_the_app_role(
    as_app_role: TestClient, owner: dict[str, str]
) -> None:
    slug = as_app_role.get(f"{API}/tenants/current", headers=owner).json()["slug"]
    clinic = as_app_role.get(f"{API}/public/{slug}")
    assert clinic.status_code == 200, clinic.text
    slots = as_app_role.get(f"{API}/public/{slug}/slots?type=INITIAL_CONSULT")
    assert slots.status_code == 200, slots.text
    unknown = as_app_role.get(f"{API}/public/no-such-clinic-{uuid.uuid4().hex[:6]}")
    assert unknown.status_code == 404
