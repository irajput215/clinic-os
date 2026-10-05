"""The denial paths — written first, because a route that only works is not evidence.

Requirements: `docs/features/05-patients/01-requirements.md` R2 (unknown fields rejected,
zero rows written), R6 (cross-tenant read is `404`, never `403`), R11 (no hard delete).
Design: ".../03-design.md", "Deny-by-default request path" and the negative decision matrix
in `01-requirements.md`.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.patients.conftest import DEFAULT_PATIENT, PATIENTS_URL, PatientsApi

# Fields the design does not expose in a write body, each with a plausible value: if the
# schema ever loosens, one of these would otherwise be accepted silently (R2).
FORBIDDEN_BODY_FIELDS: dict[str, object] = {
    "tenant_id": str(uuid.uuid4()),
    "deleted_at": "2020-01-01T00:00:00Z",
    "merged_into_patient_id": str(uuid.uuid4()),
    "id": str(uuid.uuid4()),
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2020-01-01T00:00:00Z",
}


def _unknown_uuid() -> str:
    return str(uuid.uuid4())


def test_unauthenticated_request_is_rejected(client: TestClient) -> None:
    """Step 1 of the request path: authenticate the session, deny if missing."""
    assert client.post(PATIENTS_URL, json=DEFAULT_PATIENT).status_code == 401
    assert client.get(PATIENTS_URL).status_code == 401
    assert client.get(f"{PATIENTS_URL}/{_unknown_uuid()}").status_code == 401
    assert (
        client.patch(
            f"{PATIENTS_URL}/{_unknown_uuid()}", json={"given_name": "Mallory"}
        ).status_code
        == 401
    )


def test_a_caller_without_a_tenant_fails_closed(
    client: TestClient, api: PatientsApi
) -> None:
    """An unattached account is denied — never defaulted to a tenant, never unscoped."""
    account = api.register(clinic_name=None)
    assert account.tenant_id is None

    assert (
        client.post(
            PATIENTS_URL, json=DEFAULT_PATIENT, headers=account.headers
        ).status_code
        == 403
    )
    assert client.get(PATIENTS_URL, headers=account.headers).status_code == 403
    assert (
        client.get(
            f"{PATIENTS_URL}/{_unknown_uuid()}", headers=account.headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"{PATIENTS_URL}/{_unknown_uuid()}",
            json={"given_name": "Mallory"},
            headers=account.headers,
        ).status_code
        == 403
    )


@pytest.mark.parametrize("field", sorted(FORBIDDEN_BODY_FIELDS))
def test_create_rejects_a_body_field_the_design_does_not_expose(
    api: PatientsApi, field: str
) -> None:
    """`extra="forbid"`: the field is a `422` and **no row is written** (R2)."""
    tenant = api.register(clinic_name="Riverside Family Clinic")
    assert tenant.tenant_id is not None
    before = api.patient_count(tenant.tenant_id)

    response = api.create_raw(tenant, **{field: FORBIDDEN_BODY_FIELDS[field]})

    assert response.status_code == 422, response.text
    assert field in response.text
    assert api.patient_count(tenant.tenant_id) == before


@pytest.mark.parametrize("field", ["medicare_number", "ihi"])
def test_create_rejects_an_identifier_the_slice_cannot_encrypt(
    api: PatientsApi, field: str
) -> None:
    """No identifier is mass-assignable while key custody is open (design open item 5)."""
    tenant = api.register(clinic_name="Riverside Family Clinic")
    before = api.patient_count(tenant.tenant_id)

    response = api.create_raw(tenant, **{field: "2123456789"})

    assert response.status_code == 422, response.text
    assert api.patient_count(tenant.tenant_id) == before


def test_create_rejects_a_sex_at_birth_outside_the_closed_set(
    api: PatientsApi,
) -> None:
    tenant = api.register(clinic_name="Riverside Family Clinic")
    response = api.create_raw(tenant, sex_at_birth="ROBOT")
    assert response.status_code == 422, response.text
    assert api.patient_count(tenant.tenant_id) == 0


def test_cross_tenant_read_is_404_with_no_patient_data(
    client: TestClient, api: PatientsApi
) -> None:
    """R6: `404`, never `403` — a `403` would confirm the record exists."""
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    patient_b = api.create(clinic_b, given_name="Bob", family_name="Beta")

    response = client.get(f"{PATIENTS_URL}/{patient_b['id']}", headers=clinic_a.headers)

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"detail"}
    assert body["detail"] == "Patient not found"
    for leaked in ("Beta", "Bob", patient_b["id"]):
        assert leaked not in response.text


def test_cross_tenant_patch_is_404_and_leaves_the_row_unchanged(
    client: TestClient, api: PatientsApi
) -> None:
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    patient_b = api.create(clinic_b, given_name="Bob", family_name="Beta")
    before = api.row(patient_b["id"])

    response = client.patch(
        f"{PATIENTS_URL}/{patient_b['id']}",
        json={"given_name": "Mallory", "family_name": "Forged"},
        headers=clinic_a.headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Patient not found"}
    assert api.row(patient_b["id"]) == before


def test_patch_rejects_an_unknown_field_and_changes_nothing(
    api: PatientsApi,
) -> None:
    tenant = api.register(clinic_name="Riverside Family Clinic")
    patient = api.create(tenant)
    before = api.row(patient["id"])

    response = api.patch(tenant, patient["id"], {"tenant_id": _unknown_uuid()})

    assert response.status_code == 422, response.text
    assert "tenant_id" in response.text
    assert api.row(patient["id"]) == before


def test_patch_cannot_clear_a_required_column(api: PatientsApi) -> None:
    """An explicit `null` for a NOT NULL column is `422`, not a `500` from the database."""
    tenant = api.register(clinic_name="Riverside Family Clinic")
    patient = api.create(tenant)

    response = api.patch(tenant, patient["id"], {"given_name": None})

    assert response.status_code == 422, response.text
    assert api.row(patient["id"]) is not None


def test_there_is_no_delete_route(api: PatientsApi) -> None:
    """R11: the application never hard-deletes a patient, so no route offers to."""
    tenant = api.register(clinic_name="Riverside Family Clinic")
    patient = api.create(tenant)

    response = api.client.delete(
        f"{PATIENTS_URL}/{patient['id']}", headers=tenant.headers
    )

    assert response.status_code == 405
    assert api.row(patient["id"]) is not None
