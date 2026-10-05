"""T1-30 — the access-control matrix over the Phase 1 protected routes.

The Phase 1 protected routes that exist today are the four patient routes (T1-32). For each one: an
unauthenticated request is refused `401`, a caller without the route's permission is refused `403` and
changes nothing, and a caller holding the permission succeeds. The expected rights are the
`patient:*` rows of the matrix in `docs/features/03-users-and-roles/01-requirements.md`, hard-coded
here so the test is a check on the catalogue rather than a restatement of it.

The task layer names this file (`tests/security/test_authz_matrix.py`, T1-30); the feature layer's test
plan names `tests/security/test_users_rbac.py::test_role_endpoint_matrix_403_without_permission` for
the same obligation. The task-layer name is used and the divergence is reported.
"""

import uuid
from collections.abc import Iterator
from typing import Any, NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.rbac import ActorSession, RbacApi

PATIENTS_URL = f"{settings.API_V1_STR}/patients"

DEFAULT_PATIENT: dict[str, str] = {
    "given_name": "Ada",
    "family_name": "Synthetic",
    "date_of_birth": "1990-01-01",
}

# (patient:create, patient:read, patient:update) per role, from
# `docs/features/03-users-and-roles/01-requirements.md` "Permission catalogue (role x permission)".
# `G` (with or without a resource modifier) is True; `-` is False.
ROLE_PATIENT_RIGHTS: dict[str, tuple[bool, bool, bool]] = {
    "PRACTICE_OWNER": (True, True, True),
    "AUTHORISED_PRESCRIBER": (True, True, True),
    "DOCTOR": (True, True, True),
    "NURSE": (True, True, True),
    "ADMINISTRATOR": (True, True, True),
    "PHARMACY": (False, True, False),
    "COMPLIANCE_AUDITOR": (False, True, False),
}


class Matrix(NamedTuple):
    """One tenant, one account per system role, one patient to act on."""

    api: RbacApi
    owner: ActorSession
    actors: dict[str, ActorSession]
    patient: dict[str, Any]


@pytest.fixture(scope="module")
def matrix(client: TestClient, db: Session) -> Iterator[Matrix]:
    api = RbacApi(client, db)
    owner = api.register_tenant(clinic_name="Matrix Clinic")
    assert owner.tenant_id is not None
    actors: dict[str, ActorSession] = {"PRACTICE_OWNER": owner}
    for code in ROLE_PATIENT_RIGHTS:
        if code == "PRACTICE_OWNER":
            continue
        actors[code] = api.add_actor(
            tenant_id=owner.tenant_id,
            granted_by=owner.user_id,
            role_code=code,
        )
    created = client.post(PATIENTS_URL, json=DEFAULT_PATIENT, headers=owner.headers)
    assert created.status_code == 201, created.text
    yield Matrix(api=api, owner=owner, actors=actors, patient=created.json())
    api.cleanup()


def test_unauthenticated_requests_are_refused_401(client: TestClient) -> None:
    unknown = uuid.uuid4()
    assert client.post(PATIENTS_URL, json=DEFAULT_PATIENT).status_code == 401
    assert client.get(PATIENTS_URL).status_code == 401
    assert client.get(f"{PATIENTS_URL}/{unknown}").status_code == 401
    assert (
        client.patch(
            f"{PATIENTS_URL}/{unknown}", json={"given_name": "Mallory"}
        ).status_code
        == 401
    )


def test_role_endpoint_matrix(matrix: Matrix) -> None:
    """Every role against every protected route: `403` without the permission, success with it."""
    tenant_id = matrix.owner.tenant_id
    assert tenant_id is not None
    patient_id = uuid.UUID(str(matrix.patient["id"]))

    for role, (can_create, can_read, can_update) in ROLE_PATIENT_RIGHTS.items():
        actor = matrix.actors[role]
        before = matrix.api.patient_count(tenant_id)

        # POST /patients — patient:create
        response = matrix.api.client.post(
            PATIENTS_URL,
            json={
                "given_name": f"Created by {role}",
                "family_name": "Matrix",
                "date_of_birth": "1980-06-01",
            },
            headers=actor.headers,
        )
        if can_create:
            assert response.status_code == 201, f"{role}: {response.text}"
        else:
            assert response.status_code == 403, f"{role}: {response.text}"
            assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
            assert matrix.api.patient_count(tenant_id) == before, (
                f"{role} was refused create but a row was still written"
            )

        # GET /patients — patient:read
        response = matrix.api.client.get(PATIENTS_URL, headers=actor.headers)
        assert response.status_code == (200 if can_read else 403), (
            f"{role}: {response.text}"
        )
        if not can_read:
            assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"

        # GET /patients/{id} — patient:read
        response = matrix.api.client.get(
            f"{PATIENTS_URL}/{patient_id}", headers=actor.headers
        )
        assert response.status_code == (200 if can_read else 403), (
            f"{role}: {response.text}"
        )

        # PATCH /patients/{id} — patient:update
        sentinel = f"patched-by-{role}"
        response = matrix.api.client.patch(
            f"{PATIENTS_URL}/{patient_id}",
            json={"preferred_name": sentinel},
            headers=actor.headers,
        )
        if can_update:
            assert response.status_code == 200, f"{role}: {response.text}"
            assert response.json()["preferred_name"] == sentinel
        else:
            assert response.status_code == 403, f"{role}: {response.text}"
            assert response.json()["detail"]["code"] == "PERMISSION_NOT_HELD"
            stored = matrix.api.patient_row(patient_id)
            assert stored is not None
            assert stored["preferred_name"] != sentinel, (
                f"{role} was refused update but the row changed"
            )


def test_the_matrix_covers_every_role(matrix: Matrix) -> None:
    """Guard the matrix itself: a role dropped from the table would stop being tested silently."""
    assert set(matrix.actors) == set(ROLE_PATIENT_RIGHTS)


def test_a_caller_without_an_organisation_fails_closed(rbac: RbacApi) -> None:
    account = rbac.register_tenant(clinic_name=None)
    assert account.tenant_id is None
    unknown = uuid.uuid4().hex

    assert (
        rbac.client.post(
            PATIENTS_URL, json=DEFAULT_PATIENT, headers=account.headers
        ).status_code
        == 403
    )
    assert rbac.client.get(PATIENTS_URL, headers=account.headers).status_code == 403
    assert (
        rbac.client.get(
            f"{PATIENTS_URL}/{unknown}", headers=account.headers
        ).status_code
        == 403
    )
    assert (
        rbac.client.patch(
            f"{PATIENTS_URL}/{unknown}",
            json={"given_name": "Mallory"},
            headers=account.headers,
        ).status_code
        == 403
    )


def test_a_denied_write_changes_nothing(rbac: RbacApi) -> None:
    """The denial path is asserted first, because a route that only works is not evidence."""
    owner = rbac.register_tenant(clinic_name="Denial Clinic")
    assert owner.tenant_id is not None
    created = rbac.client.post(
        PATIENTS_URL, json=DEFAULT_PATIENT, headers=owner.headers
    )
    assert created.status_code == 201, created.text
    patient_id = uuid.UUID(created.json()["id"])

    auditor = rbac.add_actor(
        tenant_id=owner.tenant_id,
        granted_by=owner.user_id,
        role_code="COMPLIANCE_AUDITOR",
    )
    before_row = rbac.patient_row(patient_id)
    before_count = rbac.patient_count(owner.tenant_id)

    refused_create = rbac.client.post(
        PATIENTS_URL,
        json={
            "given_name": "Mallory",
            "family_name": "Forged",
            "date_of_birth": "1970-01-01",
        },
        headers=auditor.headers,
    )
    refused_patch = rbac.client.patch(
        f"{PATIENTS_URL}/{patient_id}",
        json={"given_name": "Mallory"},
        headers=auditor.headers,
    )

    assert refused_create.status_code == 403
    assert refused_patch.status_code == 403
    assert rbac.patient_count(owner.tenant_id) == before_count
    assert rbac.patient_row(patient_id) == before_row


def test_a_client_supplied_tenant_value_cannot_widen_access(rbac: RbacApi) -> None:
    """INV-1: the tenant is resolved from the session; a body, query or header value is ignored."""
    alpha = rbac.register_tenant(clinic_name="Alpha Clinic")
    beta = rbac.register_tenant(clinic_name="Beta Clinic")
    assert alpha.tenant_id is not None and beta.tenant_id is not None

    alpha_patient = rbac.client.post(
        PATIENTS_URL, json=DEFAULT_PATIENT, headers=alpha.headers
    ).json()
    beta_patient = rbac.client.post(
        PATIENTS_URL, json=DEFAULT_PATIENT, headers=beta.headers
    ).json()

    # A body field the design does not expose is a 422, not a silently ignored field.
    forged_body = rbac.client.post(
        PATIENTS_URL,
        json={**DEFAULT_PATIENT, "tenant_id": str(beta.tenant_id)},
        headers=alpha.headers,
    )
    assert forged_body.status_code == 422, forged_body.text
    assert "tenant_id" in forged_body.text

    # A query parameter or header naming another tenant is ignored, so the record stays invisible.
    forged_read = rbac.client.get(
        f"{PATIENTS_URL}/{beta_patient['id']}?tenant_id={beta.tenant_id}",
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )
    assert forged_read.status_code == 404

    # Listing with another tenant asserted returns only the caller's own rows.
    listing = rbac.client.get(
        PATIENTS_URL,
        headers={**alpha.headers, "X-Tenant-Id": str(beta.tenant_id)},
    )
    assert listing.status_code == 200
    assert {row["id"] for row in listing.json()["data"]} == {alpha_patient["id"]}
