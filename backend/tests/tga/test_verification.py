"""Four-eyes: the creator of a manual entry cannot be the actor who verifies it.

R5, S7, F4, T2-13 and T2-15. The refusal is proven first, and the legitimate second-actor path is
proven second — a control is only a control if the permitted path still works.
"""

import uuid

from tests.tga.conftest import TenantWithPatient, TgaApi, problem_code


def test_the_creator_cannot_verify_their_own_entry(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """S7, T-04.10: `403 VERIFIER_CANNOT_BE_CREATOR`, nothing changed, and the refusal audited."""
    approval = api.create(clinic.owner, clinic.patient_id)

    refusal = api.activate(clinic.owner, approval, verifier=clinic.owner)
    assert refusal.status_code == 403, refusal.text
    assert problem_code(refusal) == "VERIFIER_CANNOT_BE_CREATOR"

    row = api.row(approval["id"])
    assert row["state"] == "PENDING"
    assert row["verified_by"] is None
    assert row["verified_at"] is None
    # No transition happened, so no lifecycle row was appended — the refusal is not a state change.
    assert [event["to_state"] for event in api.events(approval["id"])] == ["PENDING"]

    # The refusal is in the platform trail with the same fidelity as a success (control 6, A2).
    denials = [
        event
        for event in api.audit_events(
            tenant_id=clinic.owner.tenant_id, action="tga_approval.verify"
        )
        if event["result"] == "DENIED"
    ]
    assert len(denials) == 1
    assert denials[0]["reason"] == "VERIFIER_CANNOT_BE_CREATOR"
    assert denials[0]["resource_id"] == uuid.UUID(approval["id"])


def test_an_independent_clinician_verifies_it(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """F4, US-5: the second actor activates it, `verified_by`/`verified_at` are recorded, and the
    lifecycle carries both actors."""
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(clinic.owner, clinic.patient_id)

    verified = api.activate(clinic.owner, approval, verifier=verifier)
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["state"] == "ACTIVE"
    assert body["verified_by"] == str(verifier.user_id)
    assert body["verified_at"] is not None
    assert body["created_by"] == str(clinic.owner.user_id)

    transitions = [
        (event["from_state"], event["to_state"], event["actor_id"])
        for event in api.events(approval["id"])
    ]
    assert transitions == [
        (None, "PENDING", clinic.owner.user_id),
        ("PENDING", "ACTIVE", verifier.user_id),
    ]

    successes = [
        event
        for event in api.audit_events(
            tenant_id=clinic.owner.tenant_id, action="tga_approval.verify"
        )
        if event["result"] == "SUCCESS"
    ]
    assert len(successes) == 1
    assert successes[0]["actor_id"] == verifier.user_id
    assert successes[0]["resource_id"] == uuid.UUID(approval["id"])


def test_the_verifier_must_re_enter_the_application_number(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """T2-13, T-04.2: a verification that does not check the reference it verifies is not a check."""
    verifier = api.second_clinician(owner=clinic.owner)
    approval = api.create(clinic.owner, clinic.patient_id)

    mismatch = api.activate(
        clinic.owner,
        approval,
        verifier=verifier,
        application_number="TGA-2026-999999",
    )
    assert mismatch.status_code == 422, mismatch.text
    assert problem_code(mismatch) == "TGA_APPLICATION_NUMBER_MISMATCH"
    assert api.row(approval["id"])["state"] == "PENDING"

    # The number is required, not optional: an empty body is a `422` from the strict schema.
    missing = api.client.post(
        f"/api/v1/tga-approvals/{approval['id']}/verify",
        json={},
        headers=verifier.headers,
    )
    assert missing.status_code == 422, missing.text


def test_a_role_without_the_permission_cannot_verify(
    api: TgaApi, clinic: TenantWithPatient
) -> None:
    """Deny by default: the permission is checked on the route, and the refusal is audited."""
    # NURSE holds `tga_approval:read` and not `tga_approval:verify`.
    nurse = api.second_clinician(owner=clinic.owner, role_code="NURSE")
    approval = api.create(clinic.owner, clinic.patient_id)

    refusal = api.activate(clinic.owner, approval, verifier=nurse)
    assert refusal.status_code == 403, refusal.text
    assert problem_code(refusal) == "PERMISSION_NOT_HELD"
    assert api.row(approval["id"])["state"] == "PENDING"

    denials = api.audit_events(
        tenant_id=clinic.owner.tenant_id, action="tga_approval.verify"
    )
    assert any(
        event["result"] == "DENIED" and event["reason"] == "PERMISSION_NOT_HELD"
        for event in denials
    )


def test_an_auditor_cannot_revoke(api: TgaApi, clinic: TenantWithPatient) -> None:
    """US-7, T2-15: `COMPLIANCE_AUDITOR` reads and changes nothing.

    This is why `tga_approval:revoke` exists as its own code: reusing `tga_approval:verify` — which
    the auditor holds — would have made *"cannot change anything"* false in exactly this case.
    """
    auditor = api.second_clinician(owner=clinic.owner, role_code="COMPLIANCE_AUDITOR")
    approval = api.create(clinic.owner, clinic.patient_id)

    refusal = api.revoke(auditor, approval["id"])
    assert refusal.status_code == 403, refusal.text
    assert problem_code(refusal) == "PERMISSION_NOT_HELD"
    assert api.row(approval["id"])["state"] == "PENDING"

    # ... and the auditor can read, which is the half of US-7 that must still work.
    assert api.read(auditor, approval["id"]).status_code == 200
