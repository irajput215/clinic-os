"""Tenant isolation through the API.

Requirement R5: cross-tenant rows are **absent** from list results — an absence assertion,
not just the presence of the caller's own row. The policy that enforces this at the
database is exercised directly in `tests/isolation/test_patients_isolation.py`; these tests
prove the route does not hand a row to the wrong tenant.
"""

from tests.patients.conftest import PatientsApi


def test_list_never_contains_another_tenants_rows(api: PatientsApi) -> None:
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    patient_a = api.create(clinic_a, given_name="Ada", family_name="Alpha")
    patient_b = api.create(clinic_b, given_name="Bob", family_name="Beta")

    response = api.list(clinic_a)

    assert response.status_code == 200, response.text
    body = response.json()
    ids = {row["id"] for row in body["data"]}
    assert patient_a["id"] in ids
    assert patient_b["id"] not in ids
    assert body["count"] == 1
    assert all(row["family_name"] == "Alpha" for row in body["data"])
    assert "Beta" not in response.text


def test_list_count_is_scoped_to_the_caller(api: PatientsApi) -> None:
    """A count that spanned tenants would leak how many patients another clinic has."""
    clinic_a = api.register(clinic_name="Alpha Clinic")
    clinic_b = api.register(clinic_name="Beta Clinic")
    api.create(clinic_a)
    api.create(clinic_b)
    api.create(clinic_b)

    assert api.list(clinic_a).json()["count"] == 1
    assert api.list(clinic_b).json()["count"] == 2
