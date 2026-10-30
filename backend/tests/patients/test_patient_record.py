"""The patient record (docs3 feature 04; Platform Manual §3.2, §3.4).

Lifecycle status with its reason, alerts, emergency contacts, the communications flag, Medicare and
IHI encrypted at rest with a blind index for exact search, masked on every answer, and the
eScript-ready rule. Denial paths first.
"""

import uuid
from typing import Any

from sqlalchemy import text

from app.core.db import engine
from tests.patients.conftest import PATIENTS_URL, PatientsApi, TenantSession

MEDICARE = "2123456701"
IHI = "8003601234567890"
FULL_ADDRESS: dict[str, Any] = {
    "address_line": "14 Vulture St",
    "suburb": "West End",
    "state": "QLD",
    "postcode": "4101",
}


def _status(
    api: PatientsApi, session: TenantSession, patient_id: str, **body: Any
) -> Any:
    return api.client.post(
        f"{PATIENTS_URL}/{patient_id}/status", json=body, headers=session.headers
    )


def _updates(tenant_id: uuid.UUID | None) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT result, reason, metadata FROM audit_log WHERE tenant_id = :t"
                " AND action = 'patient.update' ORDER BY timestamp, event_id"
            ),
            {"t": tenant_id},
        ).mappings()
        return [dict(row) for row in rows]


# -- status ---------------------------------------------------------------------------------------


def test_another_tenants_patient_status_is_404(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Status Clinic A")
    other = api.register(clinic_name="Status Clinic B")
    patient = api.create(owner)
    response = _status(api, other, patient["id"], status="ARCHIVED", reason="moved")
    assert response.status_code == 404
    assert api.read(owner, patient["id"]).json()["status"] == "CURRENT"


def test_blocking_needs_a_reason_and_death_needs_a_date(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Status Clinic")
    patient = api.create(owner)
    for body in (
        {"status": "BLOCKED"},
        {"status": "ARCHIVED", "reason": ""},
        {"status": "DECEASED"},
    ):
        response = _status(api, owner, patient["id"], **body)
        assert response.status_code == 422, body
    assert api.read(owner, patient["id"]).json()["status"] == "CURRENT"


def test_an_unknown_status_is_refused(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Status Clinic")
    patient = api.create(owner)
    assert _status(api, owner, patient["id"], status="GONE").status_code == 422


def test_a_status_change_is_kept_and_audited_without_its_reason(
    api: PatientsApi,
) -> None:
    owner = api.register(clinic_name="Status Clinic")
    patient = api.create(owner)
    reason = "Repeated no-pay, see Kim"
    response = _status(api, owner, patient["id"], status="BLOCKED", reason=reason)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["status_reason"] == reason

    event = _updates(owner.tenant_id)[-1]
    assert event["result"] == "SUCCESS"
    assert event["reason"] == "STATUS_BLOCKED"
    assert reason not in str(event["metadata"])


def test_the_list_leaves_out_inactive_patients_unless_asked(api: PatientsApi) -> None:
    owner = api.register(clinic_name="List Clinic")
    active = api.create(owner, family_name="Active")
    archived = api.create(owner, family_name="Archived")
    assert (
        _status(
            api, owner, archived["id"], status="ARCHIVED", reason="moved away"
        ).status_code
        == 200
    )

    default = api.list(owner).json()
    assert [p["id"] for p in default["data"]] == [active["id"]]
    assert default["count"] == 1

    chosen = api.client.get(
        PATIENTS_URL, params={"status": "ARCHIVED"}, headers=owner.headers
    ).json()
    assert [p["id"] for p in chosen["data"]] == [archived["id"]]
    # Search still finds every status.
    found = api.search(owner, "Archived").json()
    assert [p["id"] for p in found["data"]] == [archived["id"]]


def test_an_unknown_status_filter_is_refused(api: PatientsApi) -> None:
    owner = api.register(clinic_name="List Clinic")
    response = api.client.get(
        PATIENTS_URL, params={"status": "GONE"}, headers=owner.headers
    )
    assert response.status_code == 422


# -- identifiers ----------------------------------------------------------------------------------


def test_identifiers_are_encrypted_masked_and_never_stored_in_plaintext(
    api: PatientsApi,
) -> None:
    owner = api.register(clinic_name="Identifier Clinic")
    created = api.create(
        owner, medicare_number="2123 45670 1", medicare_irn=2, ihi="8003 6012 3456 7890"
    )
    assert created["medicare_masked"] == "•••• 701"
    assert created["ihi_masked"] == "•••• 890"
    assert created["medicare_irn"] == 2
    assert "medicare_number" not in created
    assert "ihi" not in created

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT medicare_number, medicare_blind_index, ihi, ihi_blind_index"
                " FROM patients WHERE id = :id"
            ),
            {"id": uuid.UUID(created["id"])},
        ).one()
    for column in row:
        assert column is not None
        assert MEDICARE.encode() not in bytes(column)
        assert IHI.encode() not in bytes(column)

    for event in _updates(owner.tenant_id) + api.patient_reads(owner.tenant_id):
        assert MEDICARE not in str(event) and IHI not in str(event)


def test_search_finds_an_identifier_exactly_and_only_in_its_own_tenant(
    api: PatientsApi,
) -> None:
    owner = api.register(clinic_name="Identifier Clinic A")
    other = api.register(clinic_name="Identifier Clinic B")
    mine = api.create(owner, medicare_number=MEDICARE, ihi=IHI)
    api.create(owner, family_name="Nobody")
    api.create(other, medicare_number=MEDICARE)

    by_medicare = api.search(owner, MEDICARE).json()
    assert [p["id"] for p in by_medicare["data"]] == [mine["id"]]
    by_ihi = api.search(owner, "8003601234567890").json()
    assert [p["id"] for p in by_ihi["data"]] == [mine["id"]]
    assert api.search(owner, "2123456702").json()["data"] == []


def test_an_identifier_can_be_cleared(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Identifier Clinic")
    created = api.create(owner, medicare_number=MEDICARE)
    response = api.patch(owner, created["id"], {"medicare_number": None})
    assert response.status_code == 200, response.text
    assert response.json()["medicare_masked"] is None
    assert api.search(owner, MEDICARE).json()["data"] == []


def test_escript_readiness_names_what_is_missing(api: PatientsApi) -> None:
    owner = api.register(clinic_name="eScript Clinic")
    bare = api.create(owner)
    assert bare["escript_ready"] == {
        "ready": False,
        "missing": ["IHI", "SEX", "ADDRESS"],
    }
    ready = api.create(owner, ihi=IHI, sex_at_birth="FEMALE", **FULL_ADDRESS)
    assert ready["escript_ready"] == {"ready": True, "missing": []}


def test_timezone_and_comms_flag_are_validated_and_kept(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Comms Clinic")
    assert api.create_raw(owner, timezone="Mars/Olympus").status_code == 422
    created = api.create(
        owner, timezone="Australia/Perth", receives_communications=False
    )
    assert created["timezone"] == "Australia/Perth"
    assert created["receives_communications"] is False
    defaults = api.create(owner)
    assert defaults["timezone"] == "Australia/Sydney"
    assert defaults["receives_communications"] is True


# -- alerts and emergency contacts ----------------------------------------------------------------


def test_alerts_and_contacts_of_another_tenants_patient_are_404(
    api: PatientsApi,
) -> None:
    owner = api.register(clinic_name="Alert Clinic A")
    other = api.register(clinic_name="Alert Clinic B")
    patient = api.create(owner)
    for path, body in (
        ("alerts", {"text": "payment plan"}),
        (
            "emergency-contacts",
            {"name": "Kim", "relationship": "Sister", "phone": "0400"},
        ),
    ):
        url = f"{PATIENTS_URL}/{patient['id']}/{path}"
        assert api.client.get(url, headers=other.headers).status_code == 404
        assert api.client.post(url, json=body, headers=other.headers).status_code == 404


def test_an_alert_is_added_shown_and_removed_but_kept(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Alert Clinic")
    patient = api.create(owner)
    url = f"{PATIENTS_URL}/{patient['id']}/alerts"
    assert (
        api.client.post(
            url, json={"text": "x", "tone": "LOUD"}, headers=owner.headers
        ).status_code
        == 422
    )
    added = api.client.post(
        url, json={"text": "Interpreter needed", "tone": "WARN"}, headers=owner.headers
    )
    assert added.status_code == 201, added.text
    (alert,) = added.json()
    assert alert["tone"] == "WARN"

    removed = api.client.post(f"{url}/{alert['id']}/remove", headers=owner.headers)
    assert removed.status_code == 200
    assert removed.json() == []
    assert api.client.get(url, headers=owner.headers).json() == []
    again = api.client.post(f"{url}/{alert['id']}/remove", headers=owner.headers)
    assert again.status_code == 404
    with engine.connect() as conn:
        kept = conn.execute(
            text("SELECT removed_at FROM patient_alerts WHERE id = :id"),
            {"id": uuid.UUID(alert["id"])},
        ).scalar_one()
    assert kept is not None
    assert [e["metadata"] for e in _updates(owner.tenant_id)][-2:] == [
        {"changed_fields": ["alerts"]},
        {"changed_fields": ["alerts"]},
    ]


def test_an_emergency_contact_is_added_and_removed(api: PatientsApi) -> None:
    owner = api.register(clinic_name="Contact Clinic")
    patient = api.create(owner)
    url = f"{PATIENTS_URL}/{patient['id']}/emergency-contacts"
    added = api.client.post(
        url,
        json={"name": "Kim Example", "relationship": "Sister", "phone": "0412 000 111"},
        headers=owner.headers,
    )
    assert added.status_code == 201, added.text
    (contact,) = added.json()
    assert contact["relationship"] == "Sister"
    removed = api.client.post(f"{url}/{contact['id']}/remove", headers=owner.headers)
    assert removed.json() == []
