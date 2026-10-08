"""Staging and the queue read: denial paths first (FEAT-11 R1, R2, R7, R12; docs2 07 R1, R2)."""

import uuid

import pytest

from tests.prescriptions.conftest import URL, Clinic, RxApi, code


@pytest.mark.parametrize("role", ["PHARMACY", "ADMINISTRATOR", "COMPLIANCE_AUDITOR"])
def test_a_role_without_prescription_create_cannot_stage_and_is_audited(
    rx: RxApi, clinic: Clinic, role: str
) -> None:
    actor = rx.member(clinic, role)
    response = rx.stage_raw(actor, clinic)
    assert response.status_code == 403
    assert code(response) == "PERMISSION_NOT_HELD"
    assert clinic.owner.tenant_id is not None
    denied = rx.audit(clinic.owner.tenant_id, "prescription.create")
    assert [(e["result"], e["reason"]) for e in denied] == [
        ("DENIED", "PERMISSION_NOT_HELD")
    ]


@pytest.mark.parametrize(
    "field",
    [
        {"state": "SIGNED"},
        {"tenant_id": str(uuid.uuid4())},
        {"approval_id": str(uuid.uuid4())},
        {"schedule8_flag": False},
        {"signed_by": str(uuid.uuid4())},
    ],
)
def test_a_client_supplied_state_tenant_or_approval_is_refused(
    rx: RxApi, clinic: Clinic, field: dict[str, object]
) -> None:
    """FEAT-11 R2/R7, FEAT-10 R8: unknown fields are `422` and nothing is written."""
    response = rx.stage_raw(clinic.owner, clinic, **field)
    assert response.status_code == 422
    assert rx.list(clinic.owner).json()["data"] == []


@pytest.mark.parametrize(
    "field",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"repeats": 13},
        {"repeats": -1},
        {"medicine_name": "   "},
        {"dose_instruction": "line one\nline two"},
        {"tga_category": "lower case"},
        {"triage_outcome": "x" * 301},
    ],
)
def test_bounds_and_clinical_text_shape_are_enforced(
    rx: RxApi, clinic: Clinic, field: dict[str, object]
) -> None:
    response = rx.stage_raw(clinic.owner, clinic, **field)
    assert response.status_code == 422
    # The validation error never echoes the submitted value (INV-5).
    assert "line one" not in response.text


def test_the_prescriber_must_be_someone_who_can_sign(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    response = rx.stage_raw(clinic.owner, clinic, prescriber_id=str(nurse.user_id))
    assert response.status_code == 422
    assert code(response) == "PRESCRIBER_NOT_AUTHORIZED"


def test_another_tenants_patient_is_not_found(rx: RxApi, clinic: Clinic) -> None:
    other = rx.clinic("Other Clinic")
    response = rx.stage_raw(clinic.owner, clinic, patient_id=str(other.patient_id))
    assert response.status_code == 404
    assert code(response) == "PATIENT_NOT_FOUND"


def test_a_nurse_stages_a_draft_for_the_doctor(rx: RxApi, clinic: Clinic) -> None:
    """US-6: the draft is `DRAFT`, tenant from the session, drafter and prescriber recorded apart."""
    nurse = rx.member(clinic, "NURSE")
    body = rx.stage(clinic, nurse)
    assert body["state"] == "DRAFT"
    assert body["drafted_by"] == str(nurse.user_id)
    assert body["prescriber_id"] == str(clinic.owner.user_id)
    assert body["prescriber_name"] == "Practice Owner"
    assert body["patient_name"] == "Ada Synthetic"
    assert body["gate"]["matched"] is False
    assert body["gate"]["reason_code"] == "TGA_APPROVAL_NOT_FOUND"
    assert body["dispatch"] is None
    row = rx.row(body["id"])
    assert row["tenant_id"] == clinic.owner.tenant_id
    assert rx.events(body["id"]) == [(None, "DRAFT")]
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.create")
    assert event["result"] == "SUCCESS"
    assert event["payload"] == {"patient_id": str(clinic.patient_id)}


@pytest.mark.parametrize("role", ["PHARMACY", "ADMINISTRATOR", "COMPLIANCE_AUDITOR"])
def test_the_queue_read_needs_prescription_read(
    rx: RxApi, clinic: Clinic, role: str
) -> None:
    response = rx.list(rx.member(clinic, role))
    assert response.status_code == 403
    assert code(response) == "PERMISSION_NOT_HELD"


def test_the_queue_is_tenant_scoped_and_filtered(rx: RxApi, clinic: Clinic) -> None:
    other = rx.clinic("Other Clinic")
    rx.stage(other)
    mine = rx.stage(clinic)
    nurse = rx.member(clinic, "NURSE")
    listed = rx.list(nurse).json()["data"]
    assert [item["id"] for item in listed] == [mine["id"]]
    assert rx.list(nurse, state="SIGNED").json()["data"] == []
    assert len(rx.list(nurse, state=["DRAFT", "BLOCKED"]).json()["data"]) == 1
    assert rx.list(nurse, prescriber_id=str(nurse.user_id)).json()["data"] == []
    assert len(rx.list(nurse, patient_id=str(clinic.patient_id)).json()["data"]) == 1
    assert rx.list(nurse, patient_id=str(other.patient_id)).json()["data"] == []
    assert rx.list(nurse, state="NOT_A_STATE").status_code == 422


def test_the_queue_pages_by_signed_keyset(rx: RxApi, clinic: Clinic) -> None:
    ids = [rx.stage(clinic)["id"] for _ in range(3)]
    first = rx.list(clinic.owner, limit=2).json()
    assert len(first["data"]) == 2 and first["next_cursor"]
    second = rx.list(clinic.owner, limit=2, cursor=first["next_cursor"]).json()
    assert second["next_cursor"] is None
    seen = [item["id"] for item in first["data"] + second["data"]]
    assert sorted(seen) == sorted(ids)
    forged = rx.list(clinic.owner, cursor=first["next_cursor"][:-2] + "AA")
    assert forged.status_code == 422
    assert code(forged) == "INVALID_CURSOR"
    assert rx.list(clinic.owner, cursor="garbage").status_code == 422


def test_the_gate_shown_is_re_evaluated_now(rx: RxApi, clinic: Clinic) -> None:
    """docs2 07 R2: verifying an approval after staging changes the queue's answer immediately."""
    staged = rx.stage(clinic)
    assert staged["gate"]["matched"] is False
    rx.approve(clinic)
    [item] = rx.list(clinic.owner).json()["data"]
    assert item["id"] == staged["id"]
    assert item["gate"]["matched"] is True
    assert item["gate"]["validity_interval"]["bounds"] == "[)"


def test_prescribers_are_the_accounts_holding_prescription_sign(
    rx: RxApi, clinic: Clinic
) -> None:
    nurse = rx.member(clinic, "NURSE")
    response = rx.client.get(f"{URL}/prescribers", headers=nurse.headers)
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["data"]}
    assert str(clinic.owner.user_id) in ids
    assert str(clinic.verifier.user_id) in ids  # a DOCTOR
    assert str(nurse.user_id) not in ids
    pharmacy = rx.member(clinic, "PHARMACY")
    assert (
        rx.client.get(f"{URL}/prescribers", headers=pharmacy.headers).status_code == 403
    )
