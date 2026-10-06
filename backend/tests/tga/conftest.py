"""Fixtures and helpers for the Feature 08 (`tga_approvals`) tests.

Two tenants are created the way production creates them — `POST /users/signup` with a `clinic_name` —
and every approval is written through the API as an account of that tenant. Nothing here inserts an
approval "as the owner and trusts the policy to hide it": the cross-tenant cases prove the **API**
refuses to hand a row to the wrong tenant, and the raw-SQL cases deliberately run as `clinos_app`
(`SET LOCAL ROLE`) so the row-level security policy is what refuses.

Synthetic data only (`docs/reference/definition-of-done.md` §6). The category and dosage-form tokens
are the shape the check constraint requires, not clinical values.

Rows are removed at the end of each test, children first: `tga_approval_events` → `tga_approvals` →
the RBAC rows and organisations the signup created. `tga_approvals.tenant_id` and
`tga_approvals.patient_id` are `ON DELETE RESTRICT`, so leaving them behind would also break the
tenancy suite, which deletes every tenant between cases.
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
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
APPROVALS_URL = f"{API}/tga-approvals"

# Synthetic identifiers only. `CATEGORY_3` / `ORAL_OIL` are *shapes* the schema accepts (bounded,
# uppercase, no free text); the feature's controlled vocabulary is OPEN with the Clinical Safety
# Officer, so no clinical value is asserted anywhere in this suite.
DEFAULT_APPROVAL: dict[str, Any] = {
    "tga_category": "CATEGORY_3",
    "dosage_form": "ORAL_OIL",
    "approval_reference": "TGA-2026-000123",
    "creation_reason": "MANUAL_ENTRY",
    "valid_from": "2026-01-01",
    "valid_to": "2027-01-01",
}

DEFAULT_PATIENT: dict[str, Any] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}


class TgaApi:
    """Small client-side helper: register tenants, add a second clinician, and drive the TGA routes."""

    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)
        self._tenant_ids: list[uuid.UUID] = []

    # -- tenancy ------------------------------------------------------------------------------

    def register(self, *, clinic_name: str | None = None) -> ActorSession:
        actor = self.rbac.register_tenant(clinic_name=clinic_name)
        if actor.tenant_id is not None:
            self._tenant_ids.append(actor.tenant_id)
        return actor

    def second_clinician(self, *, owner: ActorSession, role_code: str = "DOCTOR") -> ActorSession:
        """A second account in the owner's organisation — the independent verifier of R5."""
        assert owner.tenant_id is not None
        return self.rbac.add_actor(
            tenant_id=owner.tenant_id,
            granted_by=owner.user_id,
            role_code=role_code,
        )

    # -- patients -----------------------------------------------------------------------------

    def create_patient(self, actor: ActorSession, **overrides: Any) -> uuid.UUID:
        response = self.client.post(
            f"{API}/patients",
            json={**DEFAULT_PATIENT, **overrides},
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text
        return uuid.UUID(response.json()["id"])

    # -- approvals ----------------------------------------------------------------------------

    def create_raw(
        self, actor: ActorSession, patient_id: uuid.UUID, **overrides: Any
    ) -> Response:
        return self.client.post(
            APPROVALS_URL,
            json={**DEFAULT_APPROVAL, "patient_id": str(patient_id), **overrides},
            headers=actor.headers,
        )

    def create(self, actor: ActorSession, patient_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
        response = self.create_raw(actor, patient_id, **overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def activate(
        self,
        actor: ActorSession,
        approval: dict[str, Any],
        *,
        verifier: ActorSession | None = None,
        application_number: str | None = None,
    ) -> Response:
        """Verify an approval as `verifier` (default: the same actor, which is refused)."""
        who = verifier or actor
        return self.client.post(
            f"{APPROVALS_URL}/{approval['id']}/verify",
            json={
                "tga_application_number": application_number
                if application_number is not None
                else approval["approval_reference"]
            },
            headers=who.headers,
        )

    def read(self, actor: ActorSession, approval_id: str) -> Response:
        return self.client.get(f"{APPROVALS_URL}/{approval_id}", headers=actor.headers)

    def list_for_patient(
        self, actor: ActorSession, patient_id: uuid.UUID, **params: Any
    ) -> Response:
        return self.client.get(
            f"{API}/patients/{patient_id}/tga-approvals",
            params=params,
            headers=actor.headers,
        )

    def revoke(
        self, actor: ActorSession, approval_id: str, *, reason_code: str | None = "CLINICAL_ERROR"
    ) -> Response:
        body: dict[str, Any] = {} if reason_code is None else {"reason_code": reason_code}
        return self.client.post(
            f"{APPROVALS_URL}/{approval_id}/revoke", json=body, headers=actor.headers
        )

    def match(
        self, actor: ActorSession, patient_id: uuid.UUID, **overrides: Any
    ) -> Response:
        body = {
            "patient_id": str(patient_id),
            "tga_category": DEFAULT_APPROVAL["tga_category"],
            "dosage_form": DEFAULT_APPROVAL["dosage_form"],
            "date_of_service": "2026-06-01",
            **overrides,
        }
        return self.client.post(
            f"{APPROVALS_URL}/match", json=body, headers=actor.headers
        )

    # -- direct database access (owner connection: bypasses RLS, by design) --------------------

    def row(self, approval_id: str) -> dict[str, Any] | None:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT * FROM tga_approvals WHERE id = :id"),
                    {"id": uuid.UUID(approval_id)},
                )
                .mappings()
                .first()
            )
            return None if row is None else dict(row)

    def events(self, approval_id: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT from_state, to_state, reason, actor_id FROM tga_approval_events"
                        " WHERE approval_id = :id ORDER BY occurred_at, id"
                    ),
                    {"id": uuid.UUID(approval_id)},
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    def audit_events(self, *, tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
        """The platform audit trail for one action, read as the owner."""
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        'SELECT action, result, reason, resource_id, actor_id, tenant_id'
                        ' FROM audit_log WHERE tenant_id = :tenant_id AND action = :action'
                        " ORDER BY \"timestamp\", event_id"
                    ),
                    {"tenant_id": tenant_id, "action": action},
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    def insert_approval(
        self,
        *,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        state: str = "PENDING",
        tga_category: str = DEFAULT_APPROVAL["tga_category"],
        dosage_form: str = DEFAULT_APPROVAL["dosage_form"],
        valid_from: str = "2026-01-01",
        valid_to: str = "2026-07-01",
        approval_reference: str = "TGA-RAW-000001",
        created_by: uuid.UUID | None = None,
        verified_by: uuid.UUID | None = None,
        verified_at: str | None = None,
        supersedes_id: uuid.UUID | None = None,
        superseded_by_id: uuid.UUID | None = None,
        revoked_reason_code: str | None = None,
    ) -> uuid.UUID:
        """Insert one row with raw SQL, so a constraint can be provoked without the service.

        `validity_interval` is deliberately **not** supplied: the trigger derives it from the dates,
        which is the property the constraint tests assert.
        """
        creator = created_by or uuid.uuid4()
        verifier = verified_by or (uuid.uuid4() if state == "ACTIVE" else None)
        # An `ACTIVE` row must carry its verification (`ck_tga_approvals_active_verified`), and the
        # verifier must differ from the creator (`ck_tga_approvals_four_eyes`).
        moment = verified_at or ("2026-01-02T00:00:00+00:00" if state == "ACTIVE" else None)
        with engine.begin() as conn:
            return uuid.UUID(
                str(
                    conn.execute(
                        text(
                            "INSERT INTO tga_approvals ("
                            " tenant_id, patient_id, tga_category, dosage_form,"
                            " approval_reference, valid_from, valid_to, state, source,"
                            " creation_reason, created_by, verified_by, verified_at,"
                            " supersedes_id, superseded_by_id, revoked_reason_code,"
                            " created_at, updated_at"
                            ") VALUES ("
                            " :tenant_id, :patient_id, :tga_category, :dosage_form,"
                            " :approval_reference, :valid_from, :valid_to, :state, 'MANUAL_ENTRY',"
                            " 'MANUAL_ENTRY', :created_by, :verified_by, :verified_at,"
                            " :supersedes_id, :superseded_by_id, :revoked_reason_code,"
                            " now(), now()"
                            ") RETURNING id"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "patient_id": patient_id,
                            "tga_category": tga_category,
                            "dosage_form": dosage_form,
                            "approval_reference": approval_reference,
                            "valid_from": valid_from,
                            "valid_to": valid_to,
                            "state": state,
                            "created_by": creator,
                            "verified_by": verifier,
                            "verified_at": moment,
                            "supersedes_id": supersedes_id,
                            "superseded_by_id": superseded_by_id,
                            "revoked_reason_code": revoked_reason_code,
                        },
                    )
                ).scalar_one()
            )

    def approval_count(self, tenant_id: uuid.UUID) -> int:
        """Rows that exist for one tenant, read as the owner — RLS cannot hide them from this."""
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM tga_approvals WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
            )

    def interval_is_derived(
        self, approval_id: str, *, valid_from: str, valid_to: str
    ) -> bool:
        """Is the stored `validity_interval` exactly the dates' own `[)` range?

        The assertion is a question to PostgreSQL, not to Python: the trigger derives the column, and
        this asks the database whether the derivation happened.
        """
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text(
                        "SELECT validity_interval = daterange(:valid_from, :valid_to, '[)')"
                        " FROM tga_approvals WHERE id = :id"
                    ),
                    {
                        "id": uuid.UUID(approval_id),
                        "valid_from": valid_from,
                        "valid_to": valid_to,
                    },
                ).scalar_one()
            )

    def cleanup(self) -> None:
        if not self._tenant_ids:
            return
        with engine.begin() as conn:
            for tenant_id in self._tenant_ids:
                # RESTRICT ordering, children first.
                conn.execute(
                    text(
                        "DELETE FROM tga_approval_events WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                conn.execute(
                    text("DELETE FROM tga_approvals WHERE tenant_id = :tenant_id"),
                    {"tenant_id": tenant_id},
                )
        self.rbac.cleanup()
        self._tenant_ids.clear()


class TenantWithPatient(NamedTuple):
    """The common starting point: one organisation, one patient, and the owner's session."""

    owner: ActorSession
    patient_id: uuid.UUID


@pytest.fixture(autouse=True)
def _open_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tests register their own organisations; the setting is not a test fixture."""
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def api(client: TestClient, db: Session) -> Iterator[TgaApi]:
    helper = TgaApi(client, db)
    yield helper
    helper.cleanup()


@pytest.fixture
def clinic(api: TgaApi) -> TenantWithPatient:
    owner = api.register(clinic_name="Synthetic Clinic A")
    return TenantWithPatient(owner=owner, patient_id=api.create_patient(owner))


def problem_code(response: Response) -> str | None:
    """The machine-readable code of a refusal, from the `application/problem+json` envelope.

    A deliberate refusal carries `detail = {code, message}` (`app.core.errors` keeps the payload the
    policy layer already returns). A `422` from a strict schema carries a *list* of validation errors
    with no values in them, so those are read by type instead — see `validation_types`.
    """
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def validation_types(response: Response) -> set[str]:
    """The `type` of every validation error in a `422`, which is where the schema's codes live."""
    detail = response.json().get("detail")
    if not isinstance(detail, list):
        return set()
    return {str(error.get("type")) for error in detail if isinstance(error, dict)}
