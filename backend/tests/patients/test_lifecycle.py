"""The success paths.

Requirement R1: `POST /api/v1/patients` returns `201` and the tenant is resolved from the
session, never the body. The rest of the file exercises list, read and patch within the
caller's own tenant.
"""

import uuid

from app.main import app
from tests.patients.conftest import PATIENTS_URL, PatientsApi


def test_create_patient_takes_the_tenant_from_the_session(
    api: PatientsApi,
) -> None:
    """R1: the row lands in the session's tenant, and no tenant is echoed back."""
    clinic = api.register(clinic_name="Riverside Family Clinic")
    assert clinic.tenant_id is not None

    created = api.create(clinic)

    assert uuid.UUID(created["id"])
    assert "tenant_id" not in created
    row = api.row(created["id"])
    assert row is not None
    assert row["tenant_id"] == clinic.tenant_id
    assert row["given_name"] == "Ada"
    assert row["deleted_at"] is None


def test_create_accepts_the_declared_vocabulary_and_optional_fields(
    api: PatientsApi,
) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")

    created = api.create(
        clinic,
        preferred_name="Addie",
        sex_at_birth="FEMALE",
        gender_identity="Woman",
        suburb="Fitzroy",
        state="VIC",
        postcode="3065",
        phone="+61390000000",
        email="ada@example.com",
    )

    assert created["sex_at_birth"] == "FEMALE"
    assert created["suburb"] == "Fitzroy"
    assert created["preferred_name"] == "Addie"


def test_create_strips_surrounding_whitespace(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")

    created = api.create(clinic, given_name="  Ada  ", family_name="  Synthetic  ")

    assert created["given_name"] == "Ada"
    assert created["family_name"] == "Synthetic"


def test_read_returns_the_created_patient(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    created = api.create(clinic)

    response = api.read(clinic, created["id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"]
    assert body["given_name"] == "Ada"
    # The response carries no identifier column: there is nothing to mask yet.
    for absent in ("medicare_number", "ihi", "tenant_id", "deleted_at"):
        assert absent not in body


def test_patch_updates_only_the_fields_sent(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    created = api.create(clinic, preferred_name="Addie")

    response = api.patch(clinic, created["id"], {"given_name": "Augusta"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["given_name"] == "Augusta"
    assert body["family_name"] == "Synthetic"
    assert body["preferred_name"] == "Addie"
    assert body["updated_at"] > created["updated_at"]


def test_patch_may_clear_a_nullable_field(api: PatientsApi) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    created = api.create(clinic, preferred_name="Addie")

    response = api.patch(clinic, created["id"], {"preferred_name": None})

    assert response.status_code == 200, response.text
    assert response.json()["preferred_name"] is None


def test_list_returns_the_tenants_patients_within_the_limit(
    api: PatientsApi,
) -> None:
    clinic = api.register(clinic_name="Riverside Family Clinic")
    for family_name in ("Alpha", "Beta", "Gamma"):
        api.create(clinic, family_name=family_name)

    response = api.list(clinic, limit=2)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 3
    assert [row["family_name"] for row in body["data"]] == ["Alpha", "Beta"]


def test_list_limit_is_capped_by_the_server_maximum(api: PatientsApi) -> None:
    """A client cannot ask for more than `MAX_PATIENTS_PAGE_SIZE` (25)."""
    clinic = api.register(clinic_name="Riverside Family Clinic")

    assert api.list(clinic, limit=25).status_code == 200
    assert api.list(clinic, limit=26).status_code == 422
    assert api.list(clinic, limit=0).status_code == 422
    assert api.list(clinic, limit=-1).status_code == 422


def test_the_four_declared_paths_are_served() -> None:
    """Exactly the declared paths, with no trailing slash and no `DELETE`."""
    openapi = app.openapi()
    # `GET /api/v1/patients/{patient_id}/tga-approvals` is feature 08's route, not this module's: the
    # design names that path, and the module that owns the resource owns the route (it is declared in
    # `app/modules/tga_approvals/router.py`). It is filtered out by its exact path — not by a name
    # pattern — so this census stays about the patients module, and stays exact: a fourth patients
    # route, or a trailing-slash variant of any of these, still fails the assertion below.
    owned_by_another_module = (f"{PATIENTS_URL}/{{patient_id}}/tga-approvals",)
    paths = sorted(
        path
        for path in openapi["paths"]
        if path.startswith(PATIENTS_URL) and path not in owned_by_another_module
    )

    assert paths == [PATIENTS_URL, f"{PATIENTS_URL}/{{patient_id}}"]
    assert set(openapi["paths"][PATIENTS_URL]) == {"post", "get"}
    assert set(openapi["paths"][f"{PATIENTS_URL}/{{patient_id}}"]) == {"get", "patch"}
