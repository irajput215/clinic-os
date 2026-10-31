"""docs3 feature 02: SOPs, versions and acknowledgement (R5-R8)."""

from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.prescriptions.conftest import Clinic, RxApi, code

API = settings.API_V1_STR


def _create(rx: RxApi, clinic: Clinic, **body: Any) -> Any:
    return rx.client.post(
        f"{API}/sops",
        json={"title": "Hand hygiene", "body": "Wash your hands.", **body},
        headers=clinic.owner.headers,
    )


def test_only_a_configurer_publishes(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    response = rx.client.post(
        f"{API}/sops",
        json={"title": "x", "body": "y"},
        headers=nurse.headers,
    )
    assert response.status_code == 403
    sop = _create(rx, clinic).json()
    revised = rx.client.post(
        f"{API}/sops/{sop['id']}/versions",
        json={"title": "x", "body": "y"},
        headers=nurse.headers,
    )
    assert revised.status_code == 403


def test_unknown_roles_are_refused(rx: RxApi, clinic: Clinic) -> None:
    response = _create(rx, clinic, applies_to_roles=["JANITOR"])
    assert response.status_code == 422


def test_an_sop_for_other_roles_is_not_found(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    doctors_only = _create(rx, clinic, applies_to_roles=["DOCTOR"]).json()
    everyone = _create(rx, clinic, title="Fire drill").json()
    listed = rx.client.get(f"{API}/sops", headers=nurse.headers).json()
    assert [s["id"] for s in listed] == [everyone["id"]]
    assert (
        rx.client.get(
            f"{API}/sops/{doctors_only['id']}", headers=nurse.headers
        ).status_code
        == 404
    )
    refused = rx.client.post(
        f"{API}/sops/{doctors_only['id']}/versions/1/acknowledge", headers=nurse.headers
    )
    assert refused.status_code == 404
    # The owner sees and edits every SOP.
    assert len(rx.client.get(f"{API}/sops", headers=clinic.owner.headers).json()) == 2


def test_a_new_version_resets_acknowledgement(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    sop = _create(rx, clinic).json()
    url = f"{API}/sops/{sop['id']}"
    first = rx.client.post(f"{url}/versions/1/acknowledge", headers=nurse.headers)
    assert first.status_code == 200
    assert first.json()["my_acknowledged_version"] == 1
    # Idempotent: a second acknowledgement is answered the same and audited once.
    again = rx.client.post(f"{url}/versions/1/acknowledge", headers=nurse.headers)
    assert again.status_code == 200
    assert clinic.owner.tenant_id is not None
    assert len(rx.audit(clinic.owner.tenant_id, "sop.acknowledge")) == 1

    revised = rx.client.post(
        f"{url}/versions",
        json={"title": "Hand hygiene", "body": "Wash your hands for 20 seconds."},
        headers=clinic.owner.headers,
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["current_version"] == 2
    assert [v["version"] for v in revised.json()["versions"]] == [2, 1]
    mine = rx.client.get(url, headers=nurse.headers).json()
    assert mine["current_version"] == 2
    assert mine["my_acknowledged_version"] == 1
    assert mine["body"] == "Wash your hands for 20 seconds."

    stale = rx.client.post(f"{url}/versions/1/acknowledge", headers=nurse.headers)
    assert stale.status_code == 409
    assert code(stale) == "NOT_CURRENT_VERSION"
    assert (
        rx.client.post(
            f"{url}/versions/2/acknowledge", headers=nurse.headers
        ).status_code
        == 200
    )
    assert [e["payload"] for e in rx.audit(clinic.owner.tenant_id, "sop.publish")] == [
        {"version": 1},
        {"version": 2},
    ]


def test_the_matrix_needs_configure_or_audit(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    sop = _create(rx, clinic).json()
    rx.client.post(
        f"{API}/sops/{sop['id']}/versions/1/acknowledge", headers=nurse.headers
    )
    assert rx.client.get(f"{API}/sops/matrix", headers=nurse.headers).status_code == 403
    matrix = rx.client.get(f"{API}/sops/matrix", headers=clinic.owner.headers)
    assert matrix.status_code == 200, matrix.text
    rows = {row["user_id"]: row for row in matrix.json()["staff"]}
    assert rows[str(nurse.user_id)]["acknowledged"] == {sop["id"]: 1}
    assert rows[str(clinic.owner.user_id)]["acknowledged"] == {}
    auditor = rx.member(clinic, "COMPLIANCE_AUDITOR")
    assert (
        rx.client.get(f"{API}/sops/matrix", headers=auditor.headers).status_code == 200
    )


def test_versions_and_acknowledgements_are_append_only(
    rx: RxApi, clinic: Clinic
) -> None:
    _create(rx, clinic)
    with engine.connect() as conn:
        grants = dict(
            conn.execute(
                text(
                    "SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type)"
                    " FROM information_schema.role_table_grants WHERE grantee = 'clinos_app'"
                    " AND table_name IN ('sop_versions', 'sop_acknowledgements',"
                    " 'practitioner_agreements') GROUP BY table_name"
                )
            ).all()
        )
    assert grants == {
        "sop_versions": "INSERT,SELECT",
        "sop_acknowledgements": "INSERT,SELECT",
        "practitioner_agreements": "INSERT,SELECT",
    }
