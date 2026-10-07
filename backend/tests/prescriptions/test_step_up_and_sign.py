"""Step-up (interim ADR-F002, server-side) and signing through the gate (FEAT-10, FEAT-11 R4-R6)."""

import uuid

import pytest
from sqlalchemy import text

from app.core.db import engine
from tests.prescriptions.conftest import API, URL, Clinic, RxApi, code

# -- step-up ---------------------------------------------------------------------------------------


def test_a_wrong_password_issues_nothing_and_is_audited(rx: RxApi, clinic: Clinic) -> None:
    staged = rx.stage(clinic)
    response = rx.step_up_raw(clinic.owner, staged["id"], password="not-the-password")
    assert response.status_code == 403  # never 401: a typo must not end the session
    assert code(response) == "STEP_UP_FAILED"
    assert "not-the-password" not in response.text
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "auth.step_up_failed")
    assert event["result"] == "DENIED"
    assert event["payload"] == {"operation": "prescription.sign"}


def test_step_up_rejects_unknown_operations_and_fields(rx: RxApi, clinic: Clinic) -> None:
    body = {"password": "x", "operation": "patient.export", "resource_id": str(uuid.uuid4())}
    headers = clinic.owner.headers
    assert rx.client.post(f"{API}/auth/step-up", json=body, headers=headers).status_code == 422
    body = {
        "password": "x",
        "operation": "prescription.sign",
        "resource_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
    }
    assert rx.client.post(f"{API}/auth/step-up", json=body, headers=headers).status_code == 422


def test_a_grant_is_stored_as_a_hash_and_audited(rx: RxApi, clinic: Clinic) -> None:
    staged = rx.stage(clinic)
    token = rx.step_up(clinic.owner, staged["id"])
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM step_up_grants")).scalars().all()
    assert token not in stored
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "auth.step_up")
    assert event["payload"] == {
        "operation": "prescription.sign",
        "mfa_method": "PASSWORD_REENTRY",
    }


def test_signing_without_a_valid_grant_is_step_up_required(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    other = rx.stage(clinic)
    dispatch_grant = rx.step_up(clinic.owner, staged["id"], "prescription.dispatch")
    other_grant = rx.step_up(clinic.owner, other["id"])
    for token in ("x" * 43, dispatch_grant, other_grant):
        response = rx.sign_raw(clinic.owner, staged["id"], token)
        assert response.status_code == 403, token
        assert code(response) == "STEP_UP_REQUIRED"
    assert rx.row(staged["id"])["state"] == "DRAFT"


def test_a_grant_is_single_use(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    token = rx.step_up(clinic.owner, staged["id"])
    assert rx.sign_raw(clinic.owner, staged["id"], token).status_code == 200
    again = rx.sign_raw(clinic.owner, staged["id"], token)
    assert again.status_code == 403
    assert code(again) == "STEP_UP_REQUIRED"


def test_an_expired_grant_is_refused(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    token = rx.step_up(clinic.owner, staged["id"])
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE step_up_grants SET issued_at = issued_at - interval '10 minutes',"
                " expires_at = expires_at - interval '10 minutes'"
            )
        )
    response = rx.sign_raw(clinic.owner, staged["id"], token)
    assert code(response) == "STEP_UP_REQUIRED"


def test_another_users_grant_cannot_be_spent(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic, prescriber_id=str(clinic.verifier.user_id))
    stolen = rx.step_up(clinic.owner, staged["id"])
    response = rx.sign_raw(clinic.verifier, staged["id"], stolen)
    assert code(response) == "STEP_UP_REQUIRED"


def test_a_grant_cannot_live_longer_than_two_minutes(clinic: Clinic) -> None:
    """The database refuses a long-lived grant even if the service were bypassed."""
    with pytest.raises(Exception, match="max_lifetime"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO step_up_grants (tenant_id, user_id, operation, resource_id,"
                " token_hash, issued_at, expires_at) VALUES (:tenant_id, :user_id,"
                " 'prescription.sign', gen_random_uuid(), repeat('a', 64), now(),"
                " now() + interval '10 minutes')"
            ),
            {"tenant_id": clinic.owner.tenant_id, "user_id": clinic.owner.user_id},
        )


# -- signing ---------------------------------------------------------------------------------------


def test_a_nurse_cannot_sign_and_the_refusal_is_audited(rx: RxApi, clinic: Clinic) -> None:
    nurse = rx.member(clinic, "NURSE")
    staged = rx.stage(clinic, nurse)
    response = rx.client.post(
        f"{URL}/{staged['id']}/sign", json={"step_up_token": "x" * 43}, headers=nurse.headers
    )
    assert response.status_code == 403
    assert code(response) == "PERMISSION_NOT_HELD"
    assert clinic.owner.tenant_id is not None
    assert [e["reason"] for e in rx.audit(clinic.owner.tenant_id, "prescription.sign")] == [
        "PERMISSION_NOT_HELD"
    ]


def test_only_the_prescriber_of_record_can_sign(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic, prescriber_id=str(clinic.verifier.user_id))
    response = rx.sign_raw(clinic.owner, staged["id"])
    assert response.status_code == 403
    assert code(response) == "NOT_PRESCRIBER_OF_RECORD"
    assert rx.row(staged["id"])["state"] == "DRAFT"


def test_another_tenants_prescription_is_404(rx: RxApi, clinic: Clinic) -> None:
    other = rx.clinic("Other Clinic")
    foreign = rx.stage(other)
    response = rx.client.post(
        f"{URL}/{foreign['id']}/sign", json={"step_up_token": "x" * 43}, headers=clinic.owner.headers
    )
    assert response.status_code == 404
    assert code(response) == "PRESCRIPTION_NOT_FOUND"
    assert rx.row(foreign["id"])["state"] == "DRAFT"


@pytest.mark.parametrize(
    ("approval", "expected"),
    [
        (None, "TGA_APPROVAL_NOT_FOUND"),
        ({"tga_category": "CATEGORY_4"}, "TGA_CATEGORY_MISMATCH"),
        ({"dosage_form": "CAPSULE"}, "TGA_DOSAGE_FORM_MISMATCH"),
        ({"valid_from": "2026-01-01", "valid_to": "2026-06-01"}, "TGA_APPROVAL_EXPIRED"),
        ({"valid_from": "2026-06-02", "valid_to": "2027-01-01"}, "TGA_APPROVAL_NOT_YET_EFFECTIVE"),
    ],
)
def test_the_gate_refuses_every_uncovered_grain_at_sign(
    rx: RxApi, clinic: Clinic, approval: dict[str, str] | None, expected: str
) -> None:
    """F1-F8 at sign: `422`, the reason as `detail.code`, the row stays `DRAFT`, one denied event.

    The expired case is the D-006 half-open boundary: `valid_to` = the date of service is outside.
    """
    if approval is not None:
        rx.approve(clinic, **approval)
    staged = rx.stage(clinic)
    response = rx.sign_raw(clinic.owner, staged["id"])
    assert response.status_code == 422
    assert code(response) == expected
    assert response.json()["detail"]["message"] == "Active TGA Approval Required"
    row = rx.row(staged["id"])
    assert row["state"] == "DRAFT" and row["signed_at"] is None
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.sign")
    assert (event["result"], event["reason"]) == ("DENIED", expected)
    assert event["payload"]["block_reason"] == expected


def test_a_pending_or_revoked_approval_does_not_cover(rx: RxApi, clinic: Clinic) -> None:
    pending = rx.tga.create(clinic.owner, clinic.patient_id, approval_reference="TGA-PEND-1")
    staged = rx.stage(clinic)
    assert code(rx.sign_raw(clinic.owner, staged["id"])) == "TGA_APPROVAL_PENDING_VERIFICATION"
    rx.tga.activate(clinic.owner, pending, verifier=clinic.verifier)
    assert rx.tga.revoke(clinic.owner, pending["id"]).status_code == 200
    assert code(rx.sign_raw(clinic.owner, staged["id"])) == "TGA_APPROVAL_REVOKED"


def test_a_covered_draft_is_signed_with_its_evidence(rx: RxApi, clinic: Clinic) -> None:
    approval = rx.approve(clinic)
    staged = rx.stage(clinic)
    response = rx.sign_raw(clinic.owner, staged["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "SIGNED"
    assert body["approval_id"] == approval["id"]
    assert body["gate"]["matched"] is True  # SIGNED still needs dispatching
    row = rx.row(staged["id"])
    assert row["signed_by"] == clinic.owner.user_id
    assert len(row["payload_hash"]) == 64
    assert rx.events(staged["id"]) == [(None, "DRAFT"), ("DRAFT", "SIGNED")]
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.sign")
    assert event["result"] == "SUCCESS"
    assert event["payload"] == {
        "patient_id": str(clinic.patient_id),
        "approval_id": approval["id"],
        "step_up": True,
    }
    again = rx.sign_raw(clinic.owner, staged["id"])
    assert again.status_code == 409
    assert code(again) == "INVALID_STATE_TRANSITION"
