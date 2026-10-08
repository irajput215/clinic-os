"""T1-34 — the treating-relationship rule on the patient routes, and the care team that feeds it.

Acceptance (`docs/tasks/01-phase-1-foundations.md` T1-34): *a clinician with no active care
relationship receives `403` with the care-relationship reason class and an audited denial; an accepted
read records the relationship id and the purpose; the rule runs under the same RLS policy as the
request and never widens to the tenant.* Decision D-007 records who the rule binds (the matrix's `cr`
cells: a doctor's or nurse's patient grants), the server-derived purpose, and the interim care-team
upkeep. Deny paths first, then the audit fields, then the tenant boundary, then the successes.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine
from tests.utils.care import care_team_url, relate
from tests.utils.rbac import ActorSession, RbacApi
from tests.utils.seeding import create_relationship

PATIENTS_URL = f"{settings.API_V1_STR}/patients"
CODE = "AUTHZ_CARE_RELATIONSHIP_DENIED"


class Clinic(NamedTuple):
    owner: ActorSession
    doctor: ActorSession
    nurse: ActorSession
    patient: uuid.UUID
    other_patient: uuid.UUID


@pytest.fixture
def rbac(client: TestClient, db: Session) -> Iterator[RbacApi]:
    helper = RbacApi(client, db)
    yield helper
    helper.cleanup()


def _clinic(rbac: RbacApi, name: str) -> Clinic:
    owner = rbac.register_tenant(clinic_name=name)
    assert owner.tenant_id is not None

    def patient(given: str) -> uuid.UUID:
        created = rbac.client.post(
            PATIENTS_URL,
            json={
                "given_name": given,
                "family_name": "Relationship",
                "date_of_birth": "1980-02-03",
            },
            headers=owner.headers,
        )
        assert created.status_code == 201, created.text
        return uuid.UUID(created.json()["id"])

    return Clinic(
        owner=owner,
        doctor=rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="DOCTOR"
        ),
        nurse=rbac.add_actor(
            tenant_id=owner.tenant_id, granted_by=owner.user_id, role_code="NURSE"
        ),
        patient=patient("Imogen"),
        other_patient=patient("Otto"),
    )


@pytest.fixture
def clinic(rbac: RbacApi) -> Clinic:
    return _clinic(rbac, "Relationship Clinic")


def _events(tenant_id: uuid.UUID | None, action: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT actor_id, action, result, reason, resource_id, metadata FROM audit_log"
                " WHERE tenant_id = :tenant_id AND action = :action"
                " ORDER BY timestamp, event_id"
            ),
            {"tenant_id": tenant_id, "action": action},
        )
        return [dict(row) for row in rows.mappings()]


def _mine(events: list[dict[str, Any]], actor: ActorSession) -> list[dict[str, Any]]:
    return [row for row in events if row["actor_id"] == actor.user_id]


# -- deny paths --------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["doctor", "nurse"])
def test_a_clinician_without_a_relationship_is_refused_and_audited(
    client: TestClient, clinic: Clinic, role: str
) -> None:
    clinician: ActorSession = getattr(clinic, role)

    response = client.get(f"{PATIENTS_URL}/{clinic.patient}", headers=clinician.headers)

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == CODE
    assert "Imogen" not in response.text
    [denied] = _mine(_events(clinic.owner.tenant_id, "patient.read"), clinician)
    assert denied["result"] == "DENIED"
    assert denied["reason"] == CODE
    assert denied["resource_id"] == clinic.patient
    assert denied["metadata"] is None


def test_an_update_without_a_relationship_is_refused_and_changes_nothing(
    client: TestClient, clinic: Clinic
) -> None:
    response = client.patch(
        f"{PATIENTS_URL}/{clinic.patient}",
        json={"preferred_name": "Mallory"},
        headers=clinic.doctor.headers,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == CODE
    owner_view = client.get(
        f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.owner.headers
    )
    assert owner_view.json()["preferred_name"] is None
    [denied] = _mine(_events(clinic.owner.tenant_id, "patient.update"), clinic.doctor)
    assert (denied["result"], denied["reason"]) == ("DENIED", CODE)


def test_an_ended_relationship_no_longer_authorises(
    client: TestClient, clinic: Clinic
) -> None:
    relationship = relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )
    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
        ).status_code
        == 200
    )

    ended = client.post(
        f"{care_team_url(clinic.patient)}/{relationship}/end",
        headers=clinic.owner.headers,
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["count"] == 0

    refused = client.get(
        f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == CODE


def test_one_clinicians_relationship_never_widens_to_a_colleague(
    client: TestClient, clinic: Clinic
) -> None:
    """Never widened to the tenant: the doctor's relationship does nothing for the nurse."""
    relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )

    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.nurse.headers
        ).status_code
        == 403
    )
    # Nor to another patient of the same practice.
    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.other_patient}", headers=clinic.doctor.headers
        ).status_code
        == 403
    )


def test_a_relationship_row_in_another_tenant_never_satisfies_the_rule(
    client: TestClient, clinic: Clinic, rbac: RbacApi
) -> None:
    """The rule reads under the request's tenant (RLS and the tenant predicate): a row naming this
    doctor and this patient but filed under another organisation authorises nothing."""
    elsewhere = rbac.register_tenant(clinic_name="Elsewhere Clinic")
    assert elsewhere.tenant_id is not None
    with engine.begin() as conn:
        create_relationship(
            conn,
            tenant_id=elsewhere.tenant_id,
            practitioner_id=clinic.doctor.user_id,
            patient_id=clinic.patient,
            active_from=datetime.now(UTC) - timedelta(hours=1),
        )

    response = client.get(
        f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == CODE


def test_across_a_tenant_boundary_the_answer_stays_404(
    client: TestClient, clinic: Clinic, rbac: RbacApi
) -> None:
    """`404`, never `403`: a doctor of another practice learns nothing about this patient, even one
    with relationships of their own."""
    other = _clinic(rbac, "Other Relationship Clinic")
    relate(
        client,
        other.owner.headers,
        patient_id=other.patient,
        practitioner_id=other.doctor.user_id,
    )

    for response in (
        client.get(f"{PATIENTS_URL}/{clinic.patient}", headers=other.doctor.headers),
        client.patch(
            f"{PATIENTS_URL}/{clinic.patient}",
            json={"preferred_name": "X"},
            headers=other.doctor.headers,
        ),
        client.get(care_team_url(clinic.patient), headers=other.owner.headers),
    ):
        assert response.status_code == 404, response.text
    # The attempt is audited in the attempting organisation's trail, as a not-found denial.
    [denied] = _mine(_events(other.owner.tenant_id, "patient.read"), other.doctor)[-1:]
    assert (denied["result"], denied["reason"]) == (
        "DENIED",
        "AUTHZ_DENIED_CROSS_TENANT",
    )
    assert _mine(_events(clinic.owner.tenant_id, "patient.read"), other.doctor) == []


def test_a_relationship_bound_clinician_cannot_change_a_care_team(
    client: TestClient, clinic: Clinic
) -> None:
    """Nobody records a relationship that grants themselves access."""
    response = client.post(
        care_team_url(clinic.patient),
        json={"practitioner_id": str(clinic.doctor.user_id)},
        headers=clinic.doctor.headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
    assert (
        client.get(
            care_team_url(clinic.patient), headers=clinic.doctor.headers
        ).status_code
        == 403
    )
    [denied] = _mine(
        _events(clinic.owner.tenant_id, "care_relationship.create"), clinic.doctor
    )
    assert (denied["result"], denied["reason"]) == ("DENIED", "PERMISSION_NOT_HELD")
    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
        ).status_code
        == 403
    )


def test_the_care_team_refuses_what_it_cannot_record(
    client: TestClient, clinic: Clinic, rbac: RbacApi
) -> None:
    url = care_team_url(clinic.patient)
    assert clinic.owner.tenant_id is not None
    administrator = rbac.add_actor(
        tenant_id=clinic.owner.tenant_id,
        granted_by=clinic.owner.user_id,
        role_code="ADMINISTRATOR",
    )

    # A tenant identifier in the body is an unknown field, never an input (INV-1).
    smuggled = client.post(
        url,
        json={
            "practitioner_id": str(clinic.doctor.user_id),
            "tenant_id": str(uuid.uuid4()),
        },
        headers=clinic.owner.headers,
    )
    assert smuggled.status_code == 422
    # Not a practitioner: an administrator holds no clinical role.
    not_clinical = client.post(
        url,
        json={"practitioner_id": str(administrator.user_id)},
        headers=clinic.owner.headers,
    )
    assert not_clinical.status_code == 422
    assert not_clinical.json()["detail"]["code"] == "PRACTITIONER_NOT_FOUND"
    # Unknown patient.
    unknown = client.post(
        care_team_url(uuid.uuid4()),
        json={"practitioner_id": str(clinic.doctor.user_id)},
        headers=clinic.owner.headers,
    )
    assert unknown.status_code == 404
    # A second active relationship for the same pair.
    relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )
    duplicate = client.post(
        url,
        json={"practitioner_id": str(clinic.doctor.user_id)},
        headers=clinic.owner.headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ALREADY_IN_CARE_TEAM"
    # Ending what is not active.
    missing = client.post(f"{url}/{uuid.uuid4()}/end", headers=clinic.owner.headers)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "RELATIONSHIP_NOT_FOUND"

    refusals = [
        row["reason"]
        for row in _events(clinic.owner.tenant_id, "care_relationship.create")
        if row["result"] == "DENIED"
    ]
    assert refusals == [
        "PRACTITIONER_NOT_FOUND",
        "PATIENT_NOT_FOUND",
        "ALREADY_IN_CARE_TEAM",
    ]


# -- audit fields -----------------------------------------------------------------------------------


def test_an_accepted_read_records_the_relationship_and_the_purpose(
    client: TestClient, clinic: Clinic
) -> None:
    relationship = relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )

    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.doctor.headers
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.owner.headers
        ).status_code
        == 200
    )

    reads = _events(clinic.owner.tenant_id, "patient.read")
    [doctor_read] = _mine(reads, clinic.doctor)
    assert doctor_read["result"] == "SUCCESS"
    assert doctor_read["resource_id"] == clinic.patient
    assert doctor_read["metadata"] == {
        "care_relationship_id": str(relationship),
        "purpose": "TREATMENT",
    }
    # The owner's grant is unconditional: the read is recorded, with the administrative purpose and
    # no relationship of their own.
    owner_reads = [
        row
        for row in _mine(reads, clinic.owner)
        if row["resource_id"] == clinic.patient
    ]
    assert owner_reads[-1]["metadata"] == {"purpose": "PRACTICE_ADMINISTRATION"}


def test_recording_and_ending_a_relationship_are_audited(
    client: TestClient, clinic: Clinic
) -> None:
    relationship = relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )
    client.post(
        f"{care_team_url(clinic.patient)}/{relationship}/end",
        headers=clinic.owner.headers,
    )

    [created] = _events(clinic.owner.tenant_id, "care_relationship.create")
    [ended] = _events(clinic.owner.tenant_id, "care_relationship.end")
    assert created["resource_id"] == clinic.patient
    assert created["metadata"] == {
        "care_relationship_id": str(relationship),
        "target_user_id": str(clinic.doctor.user_id),
        "source": "STAFF_RECORDED",
    }
    assert ended["metadata"] == {
        "care_relationship_id": str(relationship),
        "target_user_id": str(clinic.doctor.user_id),
    }
    # The row is ended, never deleted: an authorisation record that vanished would not be evidence.
    with engine.connect() as conn:
        active_to = conn.execute(
            text("SELECT active_to FROM care_relationships WHERE id = :id"),
            {"id": relationship},
        ).scalar_one()
    assert active_to is not None


# -- successes --------------------------------------------------------------------------------------


def test_with_a_relationship_the_clinician_reads_and_updates(
    client: TestClient, clinic: Clinic
) -> None:
    relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.nurse.user_id,
    )

    read = client.get(f"{PATIENTS_URL}/{clinic.patient}", headers=clinic.nurse.headers)
    assert read.status_code == 200, read.text
    assert read.json()["given_name"] == "Imogen"
    updated = client.patch(
        f"{PATIENTS_URL}/{clinic.patient}",
        json={"preferred_name": "Immy"},
        headers=clinic.nurse.headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["preferred_name"] == "Immy"


def test_a_relationship_bound_list_and_search_show_only_related_patients(
    client: TestClient, clinic: Clinic
) -> None:
    """`GET /patients` is "treating-relationship filtered" (`05-patients/03-design.md`), total included."""
    assert client.get(PATIENTS_URL, headers=clinic.doctor.headers).json()["count"] == 0
    relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )

    listed = client.get(PATIENTS_URL, headers=clinic.doctor.headers).json()
    assert [row["id"] for row in listed["data"]] == [str(clinic.patient)]
    assert listed["count"] == 1
    found = client.post(
        f"{PATIENTS_URL}/search",
        json={"q": "relationship"},
        headers=clinic.doctor.headers,
    ).json()
    assert [row["id"] for row in found["data"]] == [str(clinic.patient)]
    # The owner still sees the whole practice.
    assert client.get(PATIENTS_URL, headers=clinic.owner.headers).json()["count"] == 2
    purposes = [
        row["metadata"]["purpose"]
        for row in _mine(_events(clinic.owner.tenant_id, "patient.read"), clinic.doctor)
    ]
    assert set(purposes) == {"TREATMENT"}


def test_the_care_team_lists_its_active_members(
    client: TestClient, clinic: Clinic
) -> None:
    relate(
        client,
        clinic.owner.headers,
        patient_id=clinic.patient,
        practitioner_id=clinic.doctor.user_id,
    )

    team = client.get(care_team_url(clinic.patient), headers=clinic.owner.headers)

    assert team.status_code == 200, team.text
    [member] = team.json()["data"]
    assert member["practitioner_id"] == str(clinic.doctor.user_id)
    assert member["source"] == "STAFF_RECORDED"
