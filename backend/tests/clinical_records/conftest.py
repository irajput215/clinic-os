"""Fixtures for the Feature 06 clinical-records tests.

Every case runs against the **migrated** database and the real API. Organisations are created the
way production creates them — `POST /users/signup` with a `clinic_name`, which provisions the seven
system roles and the bootstrap `PRACTICE_OWNER` grant — and every clinical row is written through
the API as that tenant. Nothing inserts a clinical row "as the owner and trusts the policy to hide
it".

## Cleanup, and why it is `TRUNCATE`

`clinical_record_versions` is append-only **for every role**: the migration revokes
`UPDATE`/`DELETE`/`TRUNCATE` from `clinos_app` and installs a `BEFORE UPDATE OR DELETE` trigger that
raises for the owner and the migration role too. So a leaked clinical row cannot be deleted by any
role, and because `clinical_records` carries `ON DELETE RESTRICT` references to `patients`, `user`
and `tenants`, a leak would break the teardown of *every other test module* that removes those rows.

`TRUNCATE` fires no `BEFORE UPDATE OR DELETE` trigger, so it is the one statement the test owner can
use to leave the database as it found it. It is deliberately not available to the application: the
migration revokes it from `clinos_app`, which `test_immutability.py` asserts. The truncation is
scoped to the two clinical tables, which no other feature's tests write.
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
from app.main import app
from tests.utils.rbac import ActorSession, RbacApi

CLINICAL_URL = f"{settings.API_V1_STR}/clinical-records"
PATIENTS_URL = f"{settings.API_V1_STR}/patients"

# Synthetic data only (`definition-of-done.md` §6: "Test data is synthetic and classified").
DEFAULT_PATIENT: dict[str, Any] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}

# A narrative that is unambiguously synthetic and searchable in a sink.
DEFAULT_NOTE_BODY = (
    "Patient reports a mild headache. No red flags. Review in two weeks."
)

# The sentinel S12/INV-5 searches every sink for. It is a single token so a redaction filter cannot
# split it, and it appears in neither a field name nor a rule.
SENTINEL = "SENTINEL-CLINICAL-4B2E"


class ClinicalTenant(NamedTuple):
    """One signed-up organisation: the owner's session and its tenant/user identifiers."""

    tenant_id: uuid.UUID
    owner: ActorSession
    patient: uuid.UUID


class ClinicalApi:
    """Small client-side helper: sign up tenants, add role-holding actors, drive the routes."""

    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)

    # --- setup ---------------------------------------------------------------------------------

    def register(self, *, clinic_name: str = "Clinical Records Clinic") -> ActorSession:
        session = self.rbac.register_tenant(clinic_name=clinic_name)
        assert session.tenant_id is not None
        return session

    def add_actor(self, *, session: ActorSession, role_code: str) -> ActorSession:
        assert session.tenant_id is not None
        return self.rbac.add_actor(
            tenant_id=session.tenant_id,
            granted_by=session.user_id,
            role_code=role_code,
        )

    def create_patient(self, session: ActorSession, **overrides: Any) -> uuid.UUID:
        response = self.client.post(
            PATIENTS_URL,
            json={**DEFAULT_PATIENT, **overrides},
            headers=session.headers,
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    # --- the routes under test -----------------------------------------------------------------

    def create_record(
        self,
        session: ActorSession,
        patient_id: uuid.UUID,
        *,
        body: str | None = DEFAULT_NOTE_BODY,
        **extra: Any,
    ) -> Response:
        payload: dict[str, Any] = {"patient_id": str(patient_id), **extra}
        if body is not None:
            payload["body"] = body
        return self.client.post(CLINICAL_URL, json=payload, headers=session.headers)

    def read_record(self, session: ActorSession, record_id: str) -> Response:
        return self.client.get(f"{CLINICAL_URL}/{record_id}", headers=session.headers)

    def read_version(
        self, session: ActorSession, record_id: str, version: int
    ) -> Response:
        return self.client.get(
            f"{CLINICAL_URL}/{record_id}/versions/{version}",
            headers=session.headers,
        )

    def patch_record(
        self, session: ActorSession, record_id: str, **payload: Any
    ) -> Response:
        return self.client.patch(
            f"{CLINICAL_URL}/{record_id}", json=payload, headers=session.headers
        )

    def amend(self, session: ActorSession, record_id: str, **payload: Any) -> Response:
        return self.client.post(
            f"{CLINICAL_URL}/{record_id}/amendments",
            json=payload,
            headers=session.headers,
        )

    def sign(self, session: ActorSession, record_id: str) -> Response:
        return self.client.post(
            f"{CLINICAL_URL}/{record_id}/sign", headers=session.headers
        )

    def timeline(
        self, session: ActorSession, patient_id: uuid.UUID, **params: Any
    ) -> Response:
        return self.client.get(
            f"{PATIENTS_URL}/{patient_id}/clinical-records",
            params=params,
            headers=session.headers,
        )

    # --- assertions helpers --------------------------------------------------------------------

    def row_counts(self, tenant_id: uuid.UUID) -> tuple[int, int]:
        """`(records, versions)` for one tenant, read as the owner — rows that exist, not rows a
        policy would hide."""
        with engine.connect() as conn:
            records = conn.execute(
                text(
                    "SELECT count(*) FROM clinical_records WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
            versions = conn.execute(
                text(
                    "SELECT count(*) FROM clinical_record_versions"
                    " WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        return int(records), int(versions)

    def version_rows(
        self, tenant_id: uuid.UUID, record_id: str
    ) -> list[dict[str, Any]]:
        """Every version row of one record, oldest first, read as the owner."""
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id, version, body, body_format, author_id,"
                        " signed_at, supersedes_version, reason"
                        " FROM clinical_record_versions"
                        " WHERE tenant_id = :tenant_id AND clinical_record_id = :record_id"
                        " ORDER BY version"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "record_id": uuid.UUID(record_id),
                    },
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def record_row(self, tenant_id: uuid.UUID, record_id: str) -> dict[str, Any] | None:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id, tenant_id, patient_id, record_type, author_id,"
                        " current_version, signed_at FROM clinical_records"
                        " WHERE tenant_id = :tenant_id AND id = :record_id"
                    ),
                    {"tenant_id": tenant_id, "record_id": uuid.UUID(record_id)},
                )
                .mappings()
                .first()
            )
        return None if row is None else dict(row)

    def audit_rows(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every audit row of one tenant, read as the owner.

        The trail is append-only, so assertions are written against the rows a case caused, never
        against absolute counts.
        """
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT action, result, reason, resource_type, resource_id,"
                        " tenant_id, actor_id, actor_role, request_id, correlation_id,"
                        " metadata"
                        " FROM audit_log WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def clinical_events(
        self, tenant_id: uuid.UUID, *, action: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.audit_rows(tenant_id)
            if row["resource_type"] == "CLINICAL_RECORD"
            and (action is None or row["action"] == action)
        ]
        return rows

    def cleanup(self) -> None:
        """Leave the database as it was found.

        The clinical tables first — `TRUNCATE` because nothing may `DELETE` a version (see the module
        docstring) — then the organisation's own rows, which `RbacApi.cleanup` removes in the
        RESTRICT-safe order.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE clinical_records, clinical_record_versions"))
        self.rbac.cleanup()


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    """The suite's client, without `raise_server_exceptions`.

    Overrides the root `tests/conftest.py` fixture for this package only. The application registers a
    catch-all `Exception` handler (`app/core/errors.py`), so Starlette sends the `500` envelope and
    *then* re-raises — which means a client that re-raises too never lets a test observe the response.
    INV-4 has to be proved from the outside: a write whose audit row cannot be written must fail, and
    the failure must carry neither the narrative nor a traceback. That assertion is only reachable with
    the client a browser is equivalent to, which is the same reasoning (and the same argument) as
    `tests/security/test_errors_never_leak_internal_detail.py::_raising_client`.

    The 4xx assertions every other case makes are unaffected: this only changes what happens when a
    handler raises, and no case here expects an exception to escape the API.
    """
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clinical(client: TestClient, db: Session) -> Iterator[ClinicalApi]:
    """One organisation, its owner (a `PRACTICE_OWNER` holding both clinical permissions) and a
    patient in that owner's care."""
    api = ClinicalApi(client, db)
    try:
        yield api
    finally:
        api.cleanup()


@pytest.fixture
def tenant(clinical: ClinicalApi) -> ClinicalTenant:
    owner = clinical.register()
    assert owner.tenant_id is not None
    return ClinicalTenant(
        tenant_id=owner.tenant_id,
        owner=owner,
        patient=clinical.create_patient(owner),
    )


@pytest.fixture
def two_tenants(
    clinical: ClinicalApi,
) -> tuple[ClinicalTenant, ClinicalTenant]:
    """Two independent organisations, for the cross-tenant cases (S1, S2, R10)."""
    first_owner = clinical.register(clinic_name="Clinical Records Tenant A")
    second_owner = clinical.register(clinic_name="Clinical Records Tenant B")
    assert first_owner.tenant_id is not None and second_owner.tenant_id is not None
    return (
        ClinicalTenant(
            tenant_id=first_owner.tenant_id,
            owner=first_owner,
            patient=clinical.create_patient(first_owner),
        ),
        ClinicalTenant(
            tenant_id=second_owner.tenant_id,
            owner=second_owner,
            patient=clinical.create_patient(second_owner),
        ),
    )


def created_record(response: Response) -> dict[str, Any]:
    """The created record's body, with the status asserted once so every case reads the same."""
    assert response.status_code == 201, response.text
    return response.json()


# SOAP surfaces with no non-blank section. Each would otherwise render a heading-only narrative
# into the permanent record. The submitted text is whitespace, so the refusal must name the rule,
# never repeat the input.
BLANK_SOAP_SURFACES: list[dict[str, str]] = [
    {"subjective": ""},
    {"subjective": "  "},
    {"plan": "\n\t "},
    {"subjective": " ", "objective": "\n", "assessment": "\t", "plan": "   "},
]


def assert_blank_narrative_refusal(response_json: dict[str, object]) -> None:
    """The module's validation refusal: RFC 7807, `detail` narrowed to `type`/`loc`/`msg`."""
    assert response_json["status"] == 422
    detail = response_json["detail"]
    assert isinstance(detail, list) and detail
    for error in detail:
        assert set(error) <= {"type", "loc", "msg"}
    assert any("non-blank" in error["msg"] for error in detail)
