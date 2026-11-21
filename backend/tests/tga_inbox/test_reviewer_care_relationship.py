"""T2-32: a reviewer cannot accept a letter for a patient they may not access under the
care-relationship rule (D-007), and is not shown such a patient as a candidate.

No built-in role holds `tga_inbox:process` together with a relationship-bound `patient:read`, so the
reviewer here is an `Actor` whose `patient:read` is bound (it is outside `unscoped_permissions`), the
same object the policy layer builds for such a role. The checks run through the real service, the
real policy decision and the real care-relationship table.
"""

import uuid

from app.modules.tga_inbox import service
from app.modules.tga_inbox.schemas import AcceptRequest
from app.modules.users_roles.policy import Actor
from tests.tga_inbox.conftest import Clinic, InboxApi
from tests.utils.care import relate


def _bound_reviewer(clinic: Clinic, user_id: uuid.UUID) -> Actor:
    return Actor(
        user_id=user_id,
        tenant_id=clinic.tenant_id,
        is_active=True,
        permissions=frozenset({"tga_inbox:process", "patient:read"}),
        role_codes=frozenset({"BOUND_REVIEWER"}),
        # `patient:read` is held only through a relationship-bound grant.
        unscoped_permissions=frozenset({"tga_inbox:process"}),
    )


def _accept(
    reviewer: Actor,
    message_id: uuid.UUID,
    detail_attachment: str,
    patient_id: uuid.UUID,
):  # type: ignore[no-untyped-def]
    return service.accept(
        actor=reviewer,
        message_id=message_id,
        request=AcceptRequest(
            patient_id=patient_id, attachment_id=uuid.UUID(detail_attachment)
        ),
    )


def test_a_bound_reviewer_without_a_relationship_is_refused_and_sees_no_candidate(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    reviewer = _bound_reviewer(clinic, inbox.add(clinic.owner, "DOCTOR").user_id)
    claimed = service.claim(actor=reviewer, message_id=message_id)
    assert isinstance(claimed, service.InboxMessageDetail)
    # The patient matches on DOB, IHI and name, yet is not proposed to this reviewer.
    assert claimed.candidates == []

    refused = _accept(
        reviewer, message_id, str(claimed.attachments[0].id), clinic.patient_id
    )
    assert isinstance(refused, service.Refusal)
    assert (refused.status_code, refused.code) == (
        403,
        "AUTHZ_CARE_RELATIONSHIP_DENIED",
    )
    # Nothing was written, and the refusal is on the trail.
    assert (
        inbox.scalar(
            "SELECT count(*) FROM tga_approvals WHERE tenant_id = :t",
            t=clinic.tenant_id,
        )
        == 0
    )
    assert (
        inbox.scalar(
            "SELECT processing_state FROM tga_inbox_messages WHERE id = :m",
            m=message_id,
        )
        == "EXTRACTED"
    )
    denied = [
        e
        for e in inbox.audit(clinic.tenant_id, "tga_approval.verify")
        if e["result"] == "DENIED"
    ]
    assert [(e["reason"], e["resource_id"]) for e in denied] == [
        ("AUTHZ_CARE_RELATIONSHIP_DENIED", message_id)
    ]


def test_a_care_relationship_lets_the_same_reviewer_see_and_accept(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    doctor = inbox.add(clinic.owner, "DOCTOR")
    reviewer = _bound_reviewer(clinic, doctor.user_id)
    relate(
        inbox.client,
        clinic.owner.headers,
        patient_id=clinic.patient_id,
        practitioner_id=doctor.user_id,
    )
    claimed = service.claim(actor=reviewer, message_id=message_id)
    assert isinstance(claimed, service.InboxMessageDetail)
    assert [c.patient_id for c in claimed.candidates] == [clinic.patient_id]
    accepted = _accept(
        reviewer, message_id, str(claimed.attachments[0].id), clinic.patient_id
    )
    assert isinstance(accepted, service.DecisionResult), accepted
    assert accepted.processing_state == "VERIFIED"


def test_a_patient_of_another_clinic_is_404_and_audited(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    other = inbox.register()
    assert other.tenant_id is not None
    foreign_patient = inbox.create_patient(other)
    claimed = inbox.post(clinic.owner, message_id, "claim").json()
    response = inbox.post(
        clinic.owner,
        message_id,
        "accept",
        {
            "patient_id": str(foreign_patient),
            "attachment_id": claimed["attachments"][0]["id"],
        },
    )
    assert response.status_code == 404
    denied = [
        e
        for e in inbox.audit(clinic.tenant_id, "tga_approval.verify")
        if e["result"] == "DENIED"
    ]
    assert [e["reason"] for e in denied] == ["PATIENT_NOT_FOUND"]
