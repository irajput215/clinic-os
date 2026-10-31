"""docs3 feature 02: the onboarding pack, the credential vault, SOPs and the signing gate.

Denial paths first. Every identifier change needs a step-up bound to the practitioner; no value
appears in a response, an audit payload or an error.
"""

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.prescriptions.conftest import Clinic, RxApi, code
from tests.utils.onboarding import step_up

API = settings.API_V1_STR
AHPRA = "MED0001234567"


def _put(
    rx: RxApi,
    clinic: Clinic,
    user_id: uuid.UUID,
    kind: str = "AHPRA",
    *,
    token: str | None = None,
    **body: Any,
) -> Any:
    payload = {
        "value": AHPRA,
        "status": "ACTIVE",
        "verification_method": "AHPRA public register",
        **body,
    }
    payload["step_up_token"] = token or step_up(
        rx.client, clinic.owner.headers, clinic.owner.password, user_id
    )
    return rx.client.put(
        f"{API}/users/{user_id}/identifiers/{kind}",
        json=payload,
        headers=clinic.owner.headers,
    )


def _pack(client: TestClient, headers: dict[str, str], user_id: uuid.UUID) -> Any:
    return client.get(f"{API}/users/{user_id}/onboarding", headers=headers)


# -- the vault: denials ---------------------------------------------------------------------------


def test_identifier_changes_need_the_permission(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    response = rx.client.put(
        f"{API}/users/{clinic.verifier.user_id}/identifiers/AHPRA",
        json={"value": AHPRA, "status": "PENDING", "step_up_token": "x"},
        headers=nurse.headers,
    )
    assert response.status_code == 403
    assert code(response) == "PERMISSION_NOT_HELD"


def test_identifier_changes_need_a_fresh_step_up_for_that_person(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = clinic.verifier.user_id
    # No grant, a grant for another person, a grant for another operation: each refused, audited.
    for token in (
        "x" * 43,
        step_up(
            rx.client, clinic.owner.headers, clinic.owner.password, clinic.owner.user_id
        ),
        rx.step_up(clinic.owner, str(doctor), "prescription.sign"),
    ):
        response = _put(rx, clinic, doctor, token=token)
        assert response.status_code == 403, response.text
        assert code(response) == "STEP_UP_REQUIRED"
    # A grant is spent once.
    token = step_up(rx.client, clinic.owner.headers, clinic.owner.password, doctor)
    assert _put(rx, clinic, doctor, token=token).status_code == 200
    assert code(_put(rx, clinic, doctor, token=token)) == "STEP_UP_REQUIRED"
    assert clinic.owner.tenant_id is not None
    assert len(rx.audit(clinic.owner.tenant_id, "auth.step_up_failed")) >= 4


def test_a_bad_format_is_refused_before_the_step_up_is_spent(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = clinic.verifier.user_id
    token = step_up(rx.client, clinic.owner.headers, clinic.owner.password, doctor)
    for kind, value in (
        ("AHPRA", "MED123"),
        ("HPI_I", "8003600000000000"),
        ("PRESCRIBER_NUMBER", "12345"),
        ("PROVIDER_NUMBER", "1234567"),
    ):
        response = _put(rx, clinic, doctor, kind, token=token, value=value)
        assert response.status_code == 422, kind
        assert code(response) == "IDENTIFIER_FORMAT"
        assert value not in response.text
    assert _put(rx, clinic, doctor, token=token).status_code == 200


def test_active_needs_a_verification_method(rx: RxApi, clinic: Clinic) -> None:
    response = _put(rx, clinic, clinic.verifier.user_id, verification_method=None)
    assert response.status_code == 422
    assert code(response) == "VERIFICATION_REQUIRED"


def test_another_organisations_person_is_not_found(rx: RxApi, clinic: Clinic) -> None:
    other = rx.clinic("Elsewhere", ready=False)
    stranger = other.verifier.user_id
    assert _put(rx, clinic, stranger).status_code == 404
    assert _pack(rx.client, clinic.owner.headers, stranger).status_code == 404
    response = rx.client.post(
        f"{API}/users/{stranger}/agreements",
        json={"agreement_version": "2026-1", "signed_on": "2026-01-05"},
        headers=clinic.owner.headers,
    )
    assert response.status_code == 404


# -- the pack -------------------------------------------------------------------------------------


def test_only_the_person_or_a_configurer_reads_a_pack(
    rx: RxApi, clinic: Clinic
) -> None:
    nurse = rx.member(clinic, "NURSE")
    doctor = clinic.verifier
    assert _pack(rx.client, nurse.headers, doctor.user_id).status_code == 403
    own = _pack(rx.client, doctor.headers, doctor.user_id)
    assert own.status_code == 200, own.text
    assert own.json()["is_prescriber"] is True
    assert own.json()["pack_complete"] is False
    assert own.json()["missing"] == ["AGREEMENT", "AHPRA", "PRESCRIBER_NUMBER"]
    assert {i["kind"]: i["state"] for i in own.json()["identifiers"]} == {
        "AHPRA": "MISSING",
        "HPI_I": "MISSING",
        "PRESCRIBER_NUMBER": "MISSING",
        "PROVIDER_NUMBER": "MISSING",
    }
    assert clinic.owner.tenant_id is not None
    [read] = rx.audit(clinic.owner.tenant_id, "practitioner.onboarding_read")
    assert read["payload"] == {"target_user_id": str(doctor.user_id)}


def test_values_are_masked_encrypted_and_never_audited(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = clinic.verifier.user_id
    response = _put(rx, clinic, doctor, value="med 000 1234 567")
    assert response.status_code == 200, response.text
    [ahpra] = [i for i in response.json()["identifiers"] if i["kind"] == "AHPRA"]
    assert ahpra["state"] == "ACTIVE"
    assert ahpra["masked"].endswith("567")
    assert AHPRA not in response.text
    assert ahpra["verification_method"] == "AHPRA public register"
    with engine.connect() as conn:
        stored = conn.execute(
            text(
                "SELECT value_ciphertext FROM practitioner_identifiers WHERE user_id = :u"
            ),
            {"u": doctor},
        ).scalar_one()
        audited = (
            conn.execute(
                text("SELECT metadata::text FROM audit_log WHERE resource_id = :u"),
                {"u": doctor},
            )
            .scalars()
            .all()
        )
    assert AHPRA.encode() not in bytes(stored)
    assert not any(AHPRA in (payload or "") for payload in audited)
    assert clinic.owner.tenant_id is not None
    [event] = [
        e
        for e in rx.audit(clinic.owner.tenant_id, "practitioner.identifier_update")
        if e["resource_id"] == doctor
    ]
    assert event["payload"] == {
        "target_user_id": str(doctor),
        "kind": "AHPRA",
        "to_state": "ACTIVE",
        "step_up": True,
    }


def test_an_expired_or_pending_identifier_does_not_count(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = clinic.verifier.user_id
    pending = _put(rx, clinic, doctor, status="PENDING", verification_method=None)
    assert pending.status_code == 200, pending.text
    assert "AHPRA" in pending.json()["missing"]
    expired = _put(rx, clinic, doctor, value=None, expires_on="2020-01-01")
    [ahpra] = [i for i in expired.json()["identifiers"] if i["kind"] == "AHPRA"]
    assert ahpra["state"] == "EXPIRED"
    assert "AHPRA" in expired.json()["missing"]
    current = _put(rx, clinic, doctor, value=None, expires_on="2099-01-01")
    assert "AHPRA" not in current.json()["missing"]


def test_the_staff_list_shows_where_onboarding_stands(
    rx: RxApi, clinic: Clinic
) -> None:
    nurse = rx.member(clinic, "NURSE")

    def statuses() -> dict[uuid.UUID, str]:
        page = rx.client.get(f"{API}/users/staff", headers=clinic.owner.headers)
        assert page.status_code == 200, page.text
        return {
            uuid.UUID(row["id"]): row["onboarding_status"]
            for row in page.json()["data"]
        }

    before = statuses()
    assert before[nurse.user_id] == "ACTIVE"
    assert before[clinic.verifier.user_id] == "PACK_INCOMPLETE"
    rx.make_ready(clinic.owner, clinic.verifier)
    assert statuses()[clinic.verifier.user_id] == "READY"


# -- the signing gate -----------------------------------------------------------------------------


def _sign(rx: RxApi, clinic: Clinic) -> tuple[str, Any]:
    staged = rx.stage(clinic)
    return staged["id"], rx.sign_raw(clinic.owner, staged["id"])


def test_signing_is_refused_until_the_pack_is_complete(rx: RxApi) -> None:
    clinic = rx.clinic("Not Ready Clinic", ready=False)
    rx.approve(clinic)
    prescription_id, refused = _sign(rx, clinic)
    assert refused.status_code == 403, refused.text
    assert code(refused) == "PRESCRIBER_NOT_READY"
    assert refused.json()["detail"]["missing"] == [
        "AGREEMENT",
        "AHPRA",
        "PRESCRIBER_NUMBER",
    ]
    assert rx.row(prescription_id)["state"] == "DRAFT"
    assert clinic.owner.tenant_id is not None
    denied = [
        e
        for e in rx.audit(clinic.owner.tenant_id, "prescription.sign")
        if e["result"] == "DENIED"
    ]
    assert [e["reason"] for e in denied] == ["PRESCRIBER_NOT_READY"]

    # Each item alone keeps the gate shut.
    rx.client.post(
        f"{API}/users/{clinic.owner.user_id}/agreements",
        json={"agreement_version": "2026-1", "signed_on": "2026-01-05"},
        headers=clinic.owner.headers,
    )
    _, refused = _sign(rx, clinic)
    assert refused.json()["detail"]["missing"] == ["AHPRA", "PRESCRIBER_NUMBER"]

    # A required SOP for the owner's role is part of the pack too.
    rx.make_ready(clinic.owner, clinic.owner)
    sop = rx.client.post(
        f"{API}/sops",
        json={
            "title": "Prescribing standards",
            "body": "Check the approval before you sign.",
            "applies_to_roles": ["PRACTICE_OWNER", "DOCTOR"],
            "required_for_onboarding": True,
        },
        headers=clinic.owner.headers,
    )
    assert sop.status_code == 201, sop.text
    _, refused = _sign(rx, clinic)
    assert refused.json()["detail"]["missing"] == [f"SOP:{sop.json()['id']}"]

    acknowledged = rx.client.post(
        f"{API}/sops/{sop.json()['id']}/versions/1/acknowledge",
        headers=clinic.owner.headers,
    )
    assert acknowledged.status_code == 200, acknowledged.text
    prescription_id, signed = _sign(rx, clinic)
    assert signed.status_code == 200, signed.text
    assert rx.row(prescription_id)["state"] == "SIGNED"


def test_a_complete_pack_reaches_the_safety_gate_unchanged(
    rx: RxApi, clinic: Clinic
) -> None:
    # Ready, but no approval: the existing gate answers, not the pack.
    _, refused = _sign(rx, clinic)
    assert refused.status_code == 422
    assert code(refused) != "PRESCRIBER_NOT_READY"
