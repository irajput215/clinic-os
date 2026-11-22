"""The consent library (docs3 Phase 6 feature 06, R1-R4; decision D22)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from app.modules.consents.documents import PLATFORM_CONSENTS
from tests.utils.care import relate
from tests.utils.rbac import ActorSession, RbacApi

API = settings.API_V1_STR
BODY = "The clinic's own wording of this consent, long enough to be a real document for a patient."


class Api:
    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.rbac = RbacApi(client, db)
        self.tenants: list[uuid.UUID] = []

    def clinic(self) -> tuple[ActorSession, uuid.UUID]:
        owner = self.rbac.register_tenant(
            clinic_name=f"Consent Clinic {uuid.uuid4().hex[:6]}"
        )
        assert owner.tenant_id is not None
        self.tenants.append(owner.tenant_id)
        patient = self.client.post(
            f"{API}/patients",
            json={
                "given_name": "Ada",
                "family_name": "Synthetic",
                "date_of_birth": "1990-01-01",
            },
            headers=owner.headers,
        )
        assert patient.status_code == 201, patient.text
        return owner, uuid.UUID(patient.json()["id"])

    def add(self, owner: ActorSession, role: str) -> ActorSession:
        assert owner.tenant_id is not None
        return self.rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code=role
        )

    def library(self, actor: ActorSession) -> Response:
        return self.client.get(f"{API}/consents", headers=actor.headers)

    def publish(
        self, actor: ActorSession, kind: str = "TELEHEALTH", body: str = BODY
    ) -> Response:
        return self.client.post(
            f"{API}/consents/{kind}/versions",
            json={"title": "Telehealth consent (clinic)", "body": body},
            headers=actor.headers,
        )

    def status(self, actor: ActorSession, patient: uuid.UUID) -> Response:
        return self.client.get(
            f"{API}/patients/{patient}/consents", headers=actor.headers
        )

    def record(
        self, actor: ActorSession, patient: uuid.UUID, kind: str, version: str
    ) -> Response:
        return self.client.post(
            f"{API}/patients/{patient}/consents",
            json={"kind": kind, "version": version},
            headers=actor.headers,
        )

    def withdraw(
        self, actor: ActorSession, patient: uuid.UUID, kind: str, method: str = "PHONE"
    ) -> Response:
        return self.client.post(
            f"{API}/patients/{patient}/consents/{kind}/withdraw",
            json={"method": method},
            headers=actor.headers,
        )

    def audit(self, tenant: uuid.UUID, action: str) -> list[dict[str, Any]]:
        with engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT result, reason, metadata AS payload FROM audit_log"
                        ' WHERE tenant_id = :t AND action = :a ORDER BY "timestamp"'
                    ),
                    {"t": tenant, "a": action},
                ).mappings()
            ]

    def cleanup(self) -> None:
        if self.tenants:
            with engine.begin() as conn:
                for table in (
                    "consent_withdrawals",
                    "patient_consents",
                    "consent_versions",
                ):
                    conn.execute(
                        text(f"DELETE FROM {table} WHERE tenant_id = ANY(:ids)"),
                        {"ids": self.tenants},
                    )  # noqa: S608
        self.rbac.cleanup()


@pytest.fixture(autouse=True)
def _open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "USERS_OPEN_REGISTRATION", True)


@pytest.fixture
def api(client: TestClient, db: Session) -> Iterator[Api]:
    helper = Api(client, db)
    yield helper
    helper.cleanup()


def _kind(status: Response, kind: str) -> dict[str, Any]:
    return next(k for k in status.json()["kinds"] if k["kind"] == kind)


def test_a_clinic_starts_on_the_platform_defaults(api: Api) -> None:
    owner, patient = api.clinic()
    library = api.library(owner).json()["kinds"]
    assert [
        (k["kind"], k["current"]["source"], k["clinic_versions"]) for k in library
    ] == [
        ("PRIVACY", "PLATFORM", []),
        ("TELEHEALTH", "PLATFORM", []),
        ("TREATMENT", "PLATFORM", []),
    ]
    assert {k["status"] for k in api.status(owner, patient).json()["kinds"]} == {
        "NOT_GIVEN"
    }


def test_publishing_replaces_the_default_and_old_consents_need_re_consent(
    api: Api,
) -> None:
    owner, patient = api.clinic()
    platform = PLATFORM_CONSENTS["TELEHEALTH"].version
    assert api.record(owner, patient, "TELEHEALTH", platform).status_code == 200
    assert _kind(api.status(owner, patient), "TELEHEALTH")["status"] == "CURRENT"

    published = api.publish(owner)
    assert published.status_code == 201, published.text
    assert (published.json()["version"], published.json()["source"]) == (
        "clinic-1",
        "CLINIC",
    )
    # Nothing is assumed: the patient agreed to the old text.
    telehealth = _kind(api.status(owner, patient), "TELEHEALTH")
    assert (telehealth["status"], telehealth["current_version"], telehealth["signed_version"]) == (
        "NEEDS_RECONSENT", "clinic-1", platform,
    )  # fmt: skip
    library = {k["kind"]: k for k in api.library(owner).json()["kinds"]}
    assert library["TELEHEALTH"]["patients_needing_reconsent"] == 1
    # The old version can no longer be recorded; the current one can.
    stale = api.record(owner, patient, "TELEHEALTH", platform)
    assert (stale.status_code, stale.json()["detail"]["code"]) == (
        409,
        "CONSENT_VERSION_STALE",
    )
    assert api.record(owner, patient, "TELEHEALTH", "clinic-1").status_code == 200
    assert _kind(api.status(owner, patient), "TELEHEALTH")["status"] == "CURRENT"
    assert api.publish(owner).json()["version"] == "clinic-2"


def test_the_public_application_offers_the_clinics_version(api: Api) -> None:
    owner, _ = api.clinic()
    api.publish(owner)
    with engine.connect() as conn:
        slug = conn.execute(
            text("SELECT slug FROM tenants WHERE id = :t"), {"t": owner.tenant_id}
        ).scalar_one()
    form = api.client.get(f"{API}/public/{slug}/intake-form").json()
    versions = {c["kind"]: c["version"] for c in form["consents"]}
    assert versions["TELEHEALTH"] == "clinic-1"
    assert versions["PRIVACY"] == PLATFORM_CONSENTS["PRIVACY"].version


def test_withdrawal_is_recorded_and_a_later_consent_supersedes_it(api: Api) -> None:
    owner, patient = api.clinic()
    nothing = api.withdraw(owner, patient, "TREATMENT")
    assert (nothing.status_code, nothing.json()["detail"]["code"]) == (
        409,
        "NOTHING_TO_WITHDRAW",
    )
    api.record(owner, patient, "TREATMENT", PLATFORM_CONSENTS["TREATMENT"].version)
    withdrawn = api.withdraw(owner, patient, "TREATMENT", "WRITTEN")
    assert withdrawn.status_code == 200, withdrawn.text
    treatment = _kind(withdrawn, "TREATMENT")
    assert treatment["status"] == "WITHDRAWN" and treatment["withdrawn_at"] is not None
    assert "No new treatment" in treatment["stops"]
    assert api.withdraw(owner, patient, "TREATMENT").status_code == 409
    api.record(owner, patient, "TREATMENT", PLATFORM_CONSENTS["TREATMENT"].version)
    status = api.status(owner, patient)
    assert _kind(status, "TREATMENT")["status"] == "CURRENT"
    assert [e["event"] for e in status.json()["history"]] == [
        "CONSENTED",
        "WITHDRAWN",
        "CONSENTED",
    ]
    assert api.withdraw(owner, patient, "TREATMENT", "EMAIL").status_code == 422


def test_audit_names_ids_and_versions_never_text(api: Api) -> None:
    owner, patient = api.clinic()
    assert owner.tenant_id is not None
    api.publish(owner)
    api.record(owner, patient, "PRIVACY", PLATFORM_CONSENTS["PRIVACY"].version)
    api.withdraw(owner, patient, "PRIVACY")
    [published] = api.audit(owner.tenant_id, "consent.publish")
    assert published["payload"] == {"kind": "TELEHEALTH", "version": "clinic-1"}
    for action in ("consent.record", "consent.withdraw"):
        [event] = api.audit(owner.tenant_id, action)
        assert event["payload"] == {"patient_id": str(patient)}
    assert BODY not in str(api.audit(owner.tenant_id, "consent.publish"))


def test_only_tenant_configure_publishes(api: Api) -> None:
    owner, _ = api.clinic()
    assert owner.tenant_id is not None
    doctor = api.add(owner, "DOCTOR")
    assert api.publish(doctor).status_code == 403
    assert api.library(doctor).status_code == 403
    denied = [
        e
        for e in api.audit(owner.tenant_id, "consent.publish")
        if e["result"] == "DENIED"
    ]
    assert denied and denied[0]["reason"] == "PERMISSION_NOT_HELD"
    assert api.publish(owner, body="too short").status_code == 422
    assert api.publish(owner, kind="MARKETING").status_code == 422


def test_care_relationship_and_clinic_boundaries(api: Api) -> None:
    owner, patient = api.clinic()
    nurse = api.add(owner, "NURSE")
    version = PLATFORM_CONSENTS["PRIVACY"].version
    assert api.status(nurse, patient).status_code == 403
    assert api.record(nurse, patient, "PRIVACY", version).status_code == 403
    relate(api.client, owner.headers, patient_id=patient, practitioner_id=nurse.user_id)
    assert api.record(nurse, patient, "PRIVACY", version).status_code == 200
    stranger, _ = api.clinic()
    assert api.status(stranger, patient).status_code == 404
    assert api.record(stranger, patient, "PRIVACY", version).status_code == 404
    assert api.withdraw(stranger, patient, "PRIVACY").status_code == 404


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE patient_consents SET version = 'x'",
        "DELETE FROM patient_consents",
        "UPDATE consent_versions SET body = 'x'",
        "DELETE FROM consent_versions",
        "UPDATE consent_withdrawals SET method = 'PHONE'",
        "DELETE FROM consent_withdrawals",
    ],
)
def test_consent_history_is_append_only(statement: str) -> None:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE clinos_app"))
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(uuid.uuid4())},
        )
        with pytest.raises(ProgrammingError) as refused:
            conn.execute(text(statement))
        assert isinstance(refused.value.orig, InsufficientPrivilege)
