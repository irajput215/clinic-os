"""The TGA inbox end to end: email in, review, a `PENDING` approval out (FEAT-09, D-011)."""

import uuid

from app.core.config import settings
from app.modules.tga_inbox import adapters
from tests.tga_inbox.conftest import (
    API,
    INBOX,
    SYNTHETIC_IHI,
    Clinic,
    InboxApi,
    approval_letter,
    code,
    make_pdf,
)

# -- ingestion: the mailbox boundary -----------------------------------------------------------


def test_ingestion_is_off_without_a_token_and_refuses_a_wrong_one(
    inbox: InboxApi, clinic: Clinic, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    assert inbox.deliver(clinic.tenant_id, token="w" * 40).status_code == 401
    monkeypatch.setattr(settings, "TGA_INBOX_INGEST_TOKEN", None)
    assert inbox.deliver(clinic.tenant_id).status_code == 404
    assert (
        inbox.scalar(
            "SELECT count(*) FROM tga_inbox_messages WHERE tenant_id = :t",
            t=clinic.tenant_id,
        )
        == 0
    )


def test_an_address_that_is_no_clinics_inbox_records_nothing(
    inbox: InboxApi, clinic: Clinic
) -> None:
    assert (
        inbox.deliver(
            clinic.tenant_id,
            to_address=f"tga+{uuid.uuid4()}@{settings.TGA_INBOX_DOMAIN}",
        ).status_code
        == 404
    )
    assert (
        inbox.deliver(
            clinic.tenant_id, to_address=f"tga+{clinic.tenant_id}@elsewhere.example"
        ).status_code
        == 404
    )
    assert (
        inbox.scalar(
            "SELECT count(*) FROM tga_inbox_messages WHERE tenant_id = :t",
            t=clinic.tenant_id,
        )
        == 0
    )


def test_a_letter_is_read_into_fields_with_candidates_and_audited(
    inbox: InboxApi, clinic: Clinic
) -> None:
    response = inbox.deliver(clinic.tenant_id)
    assert response.status_code == 201, response.text
    assert response.json()["processing_state"] == "EXTRACTED"
    message_id = uuid.UUID(response.json()["message_id"])

    detail = inbox.detail(clinic.owner, message_id)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    values = {f["field_name"]: f["value"] for f in body["fields"]}
    assert values["APPROVAL_REFERENCE"] == "SAS-2026-004512"
    assert values["PATIENT_IHI"] == SYNTHETIC_IHI
    assert values["VALID_TO"] == "2027-02-28"
    assert body["subject"] == "SAS approval for Ada Synthetic"
    assert body["composite_score"] is not None
    assert [a["viewable"] for a in body["attachments"]] == [True]
    # The candidate is proposed with the identifiers that agreed, and nothing is pre-selected (R15).
    [candidate] = body["candidates"]
    assert candidate["patient_id"] == str(clinic.patient_id)
    assert set(candidate["agreed"]) == {"DOB", "IHI", "NAME"}
    assert body["patient_id"] is None

    ingest = inbox.audit(clinic.tenant_id, "tga_document.ingest")
    extract = inbox.audit(clinic.tenant_id, "tga_document.extract")
    assert [(e["result"], e["resource_id"]) for e in ingest] == [
        ("SUCCESS", message_id)
    ]
    assert [e["result"] for e in extract] == ["SUCCESS"]
    assert (
        inbox.audit(clinic.tenant_id, "tga_approval.read")[-1]["resource_id"]
        == message_id
    )


def test_phi_is_encrypted_at_rest(inbox: InboxApi, clinic: Clinic) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    subject = inbox.scalar(
        "SELECT subject FROM tga_inbox_messages WHERE id = :m", m=message_id
    )
    assert b"Ada" not in bytes(subject)
    stored = inbox.scalar(
        "SELECT string_agg(encode(raw_value, 'escape'), '') FROM tga_extraction_results r"
        " JOIN tga_inbox_attachments a ON a.id = r.attachment_id WHERE a.message_id = :m",
        m=message_id,
    )
    assert SYNTHETIC_IHI not in stored and "Synthetic" not in stored


def test_a_redelivery_is_the_same_message(inbox: InboxApi, clinic: Clinic) -> None:
    first = inbox.deliver(
        clinic.tenant_id, provider_message_id="<same@tga.example.gov.au>"
    )
    second = inbox.deliver(
        clinic.tenant_id, provider_message_id="<same@tga.example.gov.au>"
    )
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == {**first.json(), "duplicate": True}
    assert (
        inbox.scalar(
            "SELECT count(*) FROM tga_inbox_messages WHERE tenant_id = :t",
            t=clinic.tenant_id,
        )
        == 1
    )


def test_an_unauthenticated_or_unlisted_sender_is_quarantined_unread(
    inbox: InboxApi, clinic: Clinic
) -> None:
    for overrides in (
        {"dmarc_result": "FAIL", "dkim_result": "FAIL"},
        {"from_address": "approvals@tga.example.com"},
    ):
        message_id = inbox.delivered(clinic.tenant_id, **overrides)
        body = inbox.detail(clinic.owner, message_id).json()
        assert (body["processing_state"], body["state_reason"]) == (
            "FAILED",
            "UNTRUSTED_SENDER",
        )
        assert body["attachments"] == [] and body["fields"] == []
    assert {
        e["result"] for e in inbox.audit(clinic.tenant_id, "tga_document.ingest")
    } == {"DENIED"}


def test_an_infected_or_disguised_file_is_never_stored_or_parsed(
    inbox: InboxApi, clinic: Clinic, _inbox_settings: adapters.MemoryObjectStore
) -> None:
    letter = make_pdf(approval_letter())
    message_id = inbox.delivered(
        clinic.tenant_id,
        attachments=[
            ("approval.pdf", "application/pdf", letter + adapters.EICAR_SIGNATURE),
            ("approval.pdf", "application/pdf", b"MZ\x90\x00 not a pdf"),
            ("approval.exe.pdf", "application/pdf", letter),
            ("notes.docx", "application/vnd.openxmlformats", b"PK\x03\x04"),
        ],
    )
    body = inbox.detail(clinic.owner, message_id).json()
    assert [a["refusal_reason"] for a in body["attachments"]] == [
        "MALWARE_DETECTED",
        "TYPE_MISMATCH",
        "DOUBLE_EXTENSION",
        "TYPE_NOT_ALLOWED",
    ]
    assert [a["scan_state"] for a in body["attachments"]] == [
        "INFECTED",
        "NOT_SCANNED",
        "NOT_SCANNED",
        "NOT_SCANNED",
    ]
    assert not any(a["viewable"] for a in body["attachments"])
    assert (body["processing_state"], body["state_reason"]) == (
        "FAILED",
        "NO_USABLE_ATTACHMENT",
    )
    assert body["fields"] == []
    assert _inbox_settings.get(f"tga-inbox/{clinic.tenant_id}/x") is None


def test_a_scanned_letter_goes_to_a_person(inbox: InboxApi, clinic: Clinic) -> None:
    image_only = make_pdf([["."]])
    message_id = inbox.delivered(
        clinic.tenant_id, attachments=[("scan.pdf", "application/pdf", image_only)]
    )
    body = inbox.detail(clinic.owner, message_id).json()
    assert (body["processing_state"], body["state_reason"]) == (
        "FAILED",
        "NEEDS_MANUAL_READ",
    )
    assert body["attachments"][0]["text_state"] == "NO_TEXT"
    assert body["attachments"][0]["viewable"] is True


def test_the_original_is_served_only_while_its_hash_verifies(
    inbox: InboxApi, clinic: Clinic, _inbox_settings: adapters.MemoryObjectStore
) -> None:
    letter = make_pdf(approval_letter())
    message_id = inbox.delivered(
        clinic.tenant_id, attachments=[("a.pdf", "application/pdf", letter)]
    )
    attachment_id = inbox.detail(clinic.owner, message_id).json()["attachments"][0][
        "id"
    ]
    url = f"{INBOX}/attachments/{attachment_id}/content"
    response = inbox.client.get(url, headers=clinic.owner.headers)
    assert response.status_code == 200
    assert response.content == letter
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    key = next(iter(_inbox_settings._objects))
    _inbox_settings.put(key, letter + b"tampered")
    assert inbox.client.get(url, headers=clinic.owner.headers).status_code == 409


# -- review ---------------------------------------------------------------------------------------


def _accept_body(clinic: Clinic, detail: dict, **extra) -> dict:  # type: ignore[type-arg,no-untyped-def]
    return {
        "patient_id": str(clinic.patient_id),
        "attachment_id": detail["attachments"][0]["id"],
        **extra,
    }


def test_accept_creates_a_pending_approval_that_a_second_clinician_activates(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    claimed = inbox.post(clinic.owner, message_id, "claim")
    assert claimed.status_code == 200, claimed.text
    accepted = inbox.post(
        clinic.owner, message_id, "accept", _accept_body(clinic, claimed.json())
    )
    assert accepted.status_code == 200, accepted.text
    approval_id = accepted.json()["approval_id"]
    assert accepted.json()["processing_state"] == "VERIFIED"

    approval = inbox.client.get(
        f"{API}/tga-approvals/{approval_id}", headers=clinic.owner.headers
    ).json()
    assert approval["state"] == "PENDING"
    assert approval["source"] == "INBOX_EXTRACTION"
    assert (approval["tga_category"], approval["dosage_form"]) == (
        "CATEGORY_3",
        "ORAL_OIL",
    )
    assert (approval["valid_from"], approval["valid_to"]) == (
        "2026-03-01",
        "2027-02-28",
    )

    # The reviewer who accepted it cannot activate it; a second clinician can (four-eyes, R14).
    verify = {"tga_application_number": "SAS-2026-004512"}
    same = inbox.client.post(
        f"{API}/tga-approvals/{approval_id}/verify",
        json=verify,
        headers=clinic.owner.headers,
    )
    assert same.status_code == 403
    doctor = inbox.add(clinic.owner, "DOCTOR")
    other = inbox.client.post(
        f"{API}/tga-approvals/{approval_id}/verify", json=verify, headers=doctor.headers
    )
    assert other.status_code == 200, other.text
    assert other.json()["state"] == "ACTIVE"

    detail = inbox.detail(clinic.owner, message_id).json()
    assert (detail["decision_reason"], detail["approval_id"], detail["patient_id"]) == (
        "ACCEPTED",
        approval_id,
        str(clinic.patient_id),
    )
    decisions = inbox.audit(clinic.tenant_id, "tga_approval.verify")
    assert ("SUCCESS", "ACCEPTED", message_id) in [
        (e["result"], e["reason"], e["resource_id"]) for e in decisions
    ]
    accepted_count = inbox.scalar(
        "SELECT count(*) FROM tga_extraction_results r JOIN tga_inbox_attachments a"
        " ON a.id = r.attachment_id WHERE a.message_id = :m AND r.accepted_by IS NOT NULL",
        m=message_id,
    )
    assert accepted_count == 11


def test_deciding_needs_a_live_claim_and_one_reviewer_at_a_time(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    detail = inbox.detail(clinic.owner, message_id).json()
    assert (
        code(
            inbox.post(clinic.owner, message_id, "accept", _accept_body(clinic, detail))
        )
        == "CLAIM_REQUIRED"
    )
    second = inbox.add(clinic.owner, "ADMINISTRATOR")
    assert inbox.post(second, message_id, "claim").status_code == 200
    taken = inbox.post(clinic.owner, message_id, "claim")
    assert (taken.status_code, code(taken)) == (409, "CLAIMED_BY_ANOTHER")
    assert (
        inbox.post(second, message_id, "defer").json()["processing_state"]
        == "EXTRACTED"
    )
    assert inbox.post(clinic.owner, message_id, "claim").status_code == 200


def test_a_correction_needs_a_reason_and_is_recorded(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(
        clinic.tenant_id,
        attachments=[
            (
                "a.pdf",
                "application/pdf",
                make_pdf(approval_letter(form="Liquid for oral use")),
            )
        ],
    )
    detail = inbox.post(clinic.owner, message_id, "claim").json()
    body = _accept_body(clinic, detail, values={"DOSAGE_FORM": "ORAL_OIL"})
    refused = inbox.post(clinic.owner, message_id, "accept", body)
    assert (refused.status_code, code(refused)) == (422, "CORRECTION_REASON_REQUIRED")
    accepted = inbox.post(
        clinic.owner, message_id, "accept", {**body, "correction_reason": "OCR_MISREAD"}
    )
    assert accepted.status_code == 200, accepted.text
    assert (
        inbox.detail(clinic.owner, message_id).json()["decision_reason"]
        == "OCR_MISREAD"
    )
    reasons = [
        e["reason"] for e in inbox.audit(clinic.tenant_id, "tga_approval.verify")
    ]
    assert "CORRECTED" in reasons


def test_reject_needs_a_reason_code_and_ends_the_message(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    inbox.post(clinic.owner, message_id, "claim")
    assert inbox.post(clinic.owner, message_id, "reject", {}).status_code == 422
    assert (
        inbox.post(
            clinic.owner, message_id, "reject", {"reason_code": "free text!"}
        ).status_code
        == 422
    )
    rejected = inbox.post(
        clinic.owner, message_id, "reject", {"reason_code": "NOT_A_TGA_APPROVAL"}
    )
    assert rejected.json()["processing_state"] == "REJECTED"
    again = inbox.post(clinic.owner, message_id, "claim")
    assert (again.status_code, code(again)) == (409, "ALREADY_DECIDED")


def test_a_message_from_an_untrusted_sender_can_only_be_rejected(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(
        clinic.tenant_id, dmarc_result="FAIL", dkim_result="FAIL"
    )
    inbox.post(clinic.owner, message_id, "claim")
    body = {"patient_id": str(clinic.patient_id), "attachment_id": str(uuid.uuid4())}
    assert (
        code(inbox.post(clinic.owner, message_id, "accept", body)) == "UNTRUSTED_SENDER"
    )


def test_accept_refuses_missing_values_and_an_invalid_window(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(
        clinic.tenant_id,
        attachments=[
            (
                "a.pdf",
                "application/pdf",
                make_pdf(approval_letter(valid_to="sometime soon")),
            )
        ],
    )
    detail = inbox.post(clinic.owner, message_id, "claim").json()
    missing = inbox.post(
        clinic.owner, message_id, "accept", _accept_body(clinic, detail)
    )
    assert (missing.status_code, code(missing)) == (422, "MANDATORY_FIELD_MISSING")
    backwards = _accept_body(
        clinic,
        detail,
        values={"VALID_TO": "2025-01-01"},
        correction_reason="OCR_MISREAD",
    )
    assert (
        code(inbox.post(clinic.owner, message_id, "accept", backwards))
        == "INVALID_APPROVAL_VALUES"
    )
    assert (
        inbox.scalar(
            "SELECT count(*) FROM tga_approvals WHERE tenant_id = :t",
            t=clinic.tenant_id,
        )
        == 0
    )


def test_no_body_may_carry_server_owned_fields(inbox: InboxApi, clinic: Clinic) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    detail = inbox.post(clinic.owner, message_id, "claim").json()
    for extra in (
        {"tenant_id": str(uuid.uuid4())},
        {"state": "ACTIVE"},
        {"accepted_by": str(uuid.uuid4())},
    ):
        assert (
            inbox.post(
                clinic.owner,
                message_id,
                "accept",
                _accept_body(clinic, detail, **extra),
            ).status_code
            == 422
        )
    assert (
        inbox.deliver(clinic.tenant_id, tenant_id=str(uuid.uuid4())).status_code == 422
    )


# -- boundaries ------------------------------------------------------------------------------------


def test_another_clinic_sees_nothing_and_gets_404_not_403(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    attachment_id = inbox.detail(clinic.owner, message_id).json()["attachments"][0][
        "id"
    ]
    stranger = inbox.register()
    assert inbox.detail(stranger, message_id).status_code == 404
    assert inbox.post(stranger, message_id, "claim").status_code == 404
    assert (
        inbox.client.get(
            f"{INBOX}/attachments/{attachment_id}/content", headers=stranger.headers
        ).status_code
        == 404
    )
    assert (
        inbox.client.get(f"{INBOX}/messages", headers=stranger.headers).json()["count"]
        == 0
    )


def test_a_role_without_the_permission_is_refused_and_the_refusal_audited(
    inbox: InboxApi, clinic: Clinic
) -> None:
    message_id = inbox.delivered(clinic.tenant_id)
    nurse = inbox.add(clinic.owner, "NURSE")
    assert (
        inbox.client.get(f"{INBOX}/messages", headers=nurse.headers).status_code == 403
    )
    assert inbox.detail(nurse, message_id).status_code == 403
    assert inbox.post(nurse, message_id, "claim").status_code == 403
    denied = [
        e
        for e in inbox.audit(clinic.tenant_id, "tga_approval.read")
        if e["result"] == "DENIED"
    ]
    assert denied and denied[0]["reason"] == "PERMISSION_NOT_HELD"


def test_the_queue_is_oldest_first_and_the_address_names_the_clinic(
    inbox: InboxApi, clinic: Clinic
) -> None:
    first = inbox.delivered(clinic.tenant_id, received_at="2026-11-01T00:00:00+00:00")
    second = inbox.delivered(clinic.tenant_id, received_at="2026-11-02T00:00:00+00:00")
    queue = inbox.client.get(f"{INBOX}/messages", headers=clinic.owner.headers).json()
    assert [row["id"] for row in queue["data"]] == [str(first), str(second)]
    address = inbox.client.get(f"{INBOX}/address", headers=clinic.owner.headers).json()[
        "address"
    ]
    assert address == f"tga+{clinic.tenant_id}@{settings.TGA_INBOX_DOMAIN}"


def test_an_unset_sender_allow_list_trusts_nobody(
    inbox: InboxApi, clinic: Clinic, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "TGA_INBOX_ALLOWED_SENDER_DOMAINS", [])
    message_id = inbox.delivered(clinic.tenant_id)
    assert (
        inbox.detail(clinic.owner, message_id).json()["state_reason"]
        == "UNTRUSTED_SENDER"
    )
