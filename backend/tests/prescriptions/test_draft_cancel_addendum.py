"""FEAT-11 R3, R5, R8, R11, US-2/5/8/10 - edit a draft, cancel with a reason, amend by addendum, read one
prescription and its history (decision D-010).

Deny paths first, route by route: no permission (`403`), another tenant (`404`, never `403`), no care
relationship (`403 AUTHZ_CARE_RELATIONSHIP_DENIED`), not the script's own people (`403`), wrong state
(`409 INVALID_STATE_TRANSITION`), invalid body (`422`). Then the successes, with their audit events and
history rows, and the database's own refusal of what the routes never attempt.
"""

import uuid
from typing import Any

import pytest
from httpx import Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import engine
from tests.prescriptions.conftest import Clinic, RxApi, code

URL = f"{settings.API_V1_STR}/prescriptions"


def _signed(rx: RxApi, clinic: Clinic) -> dict[str, Any]:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    signed = rx.sign_raw(clinic.owner, staged["id"])
    assert signed.status_code == 200, signed.text
    return signed.json()


def _addendum(
    rx: RxApi,
    actor_headers: dict[str, str],
    prescription_id: str,
    key: str | None = "fix-1",
    **body: object,
) -> Response:
    headers = dict(actor_headers)
    if key is not None:
        headers["Idempotency-Key"] = key
    return rx.client.post(
        f"{URL}/{prescription_id}/addendum",
        json=body or {"repeats": 1},
        headers=headers,
    )


# -- deny paths ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["PHARMACY", "ADMINISTRATOR", "COMPLIANCE_AUDITOR"])
def test_without_the_permission_every_route_is_refused_and_audited(
    rx: RxApi, clinic: Clinic, role: str
) -> None:
    staged = rx.stage(clinic)
    member = rx.member(clinic, role)
    responses = [
        rx.client.get(f"{URL}/{staged['id']}", headers=member.headers),
        rx.client.get(f"{URL}/{staged['id']}/history", headers=member.headers),
        rx.client.patch(
            f"{URL}/{staged['id']}", json={"repeats": 1}, headers=member.headers
        ),
        rx.client.post(
            f"{URL}/{staged['id']}/cancel",
            json={"reason_code": "DUPLICATE"},
            headers=member.headers,
        ),
        _addendum(rx, member.headers, staged["id"]),
    ]
    assert [r.status_code for r in responses] == [403] * 5
    assert {code(r) for r in responses} == {"PERMISSION_NOT_HELD"}
    assert rx.row(staged["id"])["state"] == "DRAFT"
    assert clinic.owner.tenant_id is not None
    for action in ("prescription.read", "prescription.modify", "prescription.reject"):
        assert any(
            row["actor_id"] == member.user_id and row["result"] == "DENIED"
            for row in rx.audit(clinic.owner.tenant_id, action)
        ), action


def test_another_tenants_prescription_is_404_on_every_route(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    other = rx.clinic("Other Rx Tenant")
    responses = [
        rx.client.get(f"{URL}/{staged['id']}", headers=other.owner.headers),
        rx.client.get(f"{URL}/{staged['id']}/history", headers=other.owner.headers),
        rx.client.patch(
            f"{URL}/{staged['id']}", json={"repeats": 1}, headers=other.owner.headers
        ),
        rx.client.post(
            f"{URL}/{staged['id']}/cancel",
            json={"reason_code": "DUPLICATE"},
            headers=other.owner.headers,
        ),
        _addendum(rx, other.owner.headers, staged["id"]),
    ]
    assert [r.status_code for r in responses] == [404] * 5
    assert rx.row(staged["id"])["repeats"] == 2


def test_a_doctor_off_the_care_team_is_refused_with_the_relationship_code(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = clinic.verifier  # Doctor-only, no relationship
    staged = rx.stage(clinic, prescriber_id=str(doctor.user_id))
    responses = [
        rx.client.get(f"{URL}/{staged['id']}", headers=doctor.headers),
        rx.client.get(f"{URL}/{staged['id']}/history", headers=doctor.headers),
        rx.client.patch(
            f"{URL}/{staged['id']}", json={"repeats": 1}, headers=doctor.headers
        ),
        rx.client.post(
            f"{URL}/{staged['id']}/cancel",
            json={"reason_code": "DUPLICATE"},
            headers=doctor.headers,
        ),
    ]
    assert [r.status_code for r in responses] == [403] * 4
    assert {code(r) for r in responses} == {"AUTHZ_CARE_RELATIONSHIP_DENIED"}
    assert rx.row(staged["id"])["state"] == "DRAFT"


def test_only_the_drafter_or_the_prescriber_may_edit_or_cancel(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)  # drafted by the owner, addressed to the owner
    # Another doctor holds `prescription:modify` but neither drafted nor prescribes this script; a
    # nurse holds no prescribing code at all (doctor-only prescribing, 2026-10-31).
    doctor = rx.related_member(clinic, "DOCTOR")
    nurse = rx.related_member(clinic, "NURSE")
    for who, expected in (
        (doctor, "NOT_DRAFTER_OR_PRESCRIBER"),
        (nurse, "PERMISSION_NOT_HELD"),
    ):
        for response in (
            rx.client.patch(
                f"{URL}/{staged['id']}", json={"repeats": 1}, headers=who.headers
            ),
            rx.client.post(
                f"{URL}/{staged['id']}/cancel",
                json={"reason_code": "DUPLICATE"},
                headers=who.headers,
            ),
        ):
            assert response.status_code == 403, response.text
            assert code(response) == expected
    assert rx.row(staged["id"])["state"] == "DRAFT"


def test_only_the_prescriber_of_record_may_amend(rx: RxApi, clinic: Clinic) -> None:
    signed = _signed(rx, clinic)
    doctor = rx.related_member(clinic, "DOCTOR")
    refused = _addendum(rx, doctor.headers, signed["id"])
    assert refused.status_code == 403
    assert code(refused) == "NOT_PRESCRIBER_OF_RECORD"
    nurse = rx.related_member(clinic, "NURSE")
    assert code(_addendum(rx, nurse.headers, signed["id"])) == "PERMISSION_NOT_HELD"


def test_a_signed_script_cannot_be_edited(rx: RxApi, clinic: Clinic) -> None:
    signed = _signed(rx, clinic)
    response = rx.client.patch(
        f"{URL}/{signed['id']}", json={"repeats": 1}, headers=clinic.owner.headers
    )
    assert response.status_code == 409
    assert code(response) == "INVALID_STATE_TRANSITION"
    assert rx.row(signed["id"])["repeats"] == 2
    assert clinic.owner.tenant_id is not None
    [refused] = rx.audit(clinic.owner.tenant_id, "prescription.modify")
    assert (refused["result"], refused["reason"]) == (
        "DENIED",
        "INVALID_STATE_TRANSITION",
    )


def test_wrong_states_are_409(rx: RxApi, clinic: Clinic) -> None:
    staged = rx.stage(clinic)
    # A draft is edited, not amended.
    assert (
        code(_addendum(rx, clinic.owner.headers, staged["id"]))
        == "INVALID_STATE_TRANSITION"
    )
    # A queued script is in the outbox: it is never cancelled here.
    signed = _signed(rx, clinic)
    queued = rx.dispatch_raw(clinic.owner, signed["id"])
    assert queued.status_code == 202, queued.text
    refused = rx.client.post(
        f"{URL}/{signed['id']}/cancel",
        json={"reason_code": "DUPLICATE"},
        headers=clinic.owner.headers,
    )
    assert refused.status_code == 409
    assert (
        code(_addendum(rx, clinic.owner.headers, signed["id"]))
        == "INVALID_STATE_TRANSITION"
    )
    # A cancelled one stays cancelled.
    cancelled = rx.client.post(
        f"{URL}/{staged['id']}/cancel",
        json={"reason_code": "DUPLICATE"},
        headers=clinic.owner.headers,
    )
    assert cancelled.status_code == 200
    again = rx.client.post(
        f"{URL}/{staged['id']}/cancel",
        json={"reason_code": "DUPLICATE"},
        headers=clinic.owner.headers,
    )
    assert again.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"state": "SIGNED"},
        {"tenant_id": str(uuid.uuid4())},
        {"patient_id": str(uuid.uuid4())},
        {"medicine_name": None},
        {"repeats": 13},
        {"quantity": "0"},
        {"medicine_name": "   "},
    ],
)
def test_an_invalid_edit_is_422_and_writes_nothing(
    rx: RxApi, clinic: Clinic, body: dict[str, Any]
) -> None:
    staged = rx.stage(clinic)
    response = rx.client.patch(
        f"{URL}/{staged['id']}", json=body, headers=clinic.owner.headers
    )
    assert response.status_code == 422, response.text
    assert rx.row(staged["id"])["repeats"] == 2


def test_an_edit_to_a_prescriber_who_cannot_sign_is_422(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    nurse = rx.member(clinic, "NURSE")
    response = rx.client.patch(
        f"{URL}/{staged['id']}",
        json={"prescriber_id": str(nurse.user_id)},
        headers=clinic.owner.headers,
    )
    assert response.status_code == 422
    assert code(response) == "PRESCRIBER_NOT_AUTHORIZED"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason_code": "SUPERSEDED_BY_ADDENDUM"},
        {"reason_code": "because"},
        {"reason_code": "DUPLICATE", "note": "x"},
    ],
)
def test_a_cancel_needs_a_reason_code_a_person_may_give(
    rx: RxApi, clinic: Clinic, body: dict[str, Any]
) -> None:
    staged = rx.stage(clinic)
    response = rx.client.post(
        f"{URL}/{staged['id']}/cancel", json=body, headers=clinic.owner.headers
    )
    assert response.status_code == 422
    assert rx.row(staged["id"])["state"] == "DRAFT"


def test_an_addendum_needs_an_intent_key_and_a_change(
    rx: RxApi, clinic: Clinic
) -> None:
    signed = _signed(rx, clinic)
    missing = _addendum(rx, clinic.owner.headers, signed["id"], key=None)
    assert missing.status_code == 422
    assert code(missing) == "IDEMPOTENCY_KEY_REQUIRED"
    nothing = rx.client.post(
        f"{URL}/{signed['id']}/addendum",
        json={},
        headers={**clinic.owner.headers, "Idempotency-Key": "k"},
    )
    assert nothing.status_code == 422
    assert rx.row(signed["id"])["state"] == "SIGNED"


# -- successes ---------------------------------------------------------------------------------------


def test_a_draft_is_edited_and_the_event_names_fields_not_values(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    response = rx.client.patch(
        f"{URL}/{staged['id']}",
        json={
            "dose_instruction": "1 mL nocte",
            "repeats": 3,
            "prescriber_id": str(clinic.verifier.user_id),
        },
        headers=clinic.owner.headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["dose_instruction"], body["repeats"], body["state"]) == (
        "1 mL nocte",
        3,
        "DRAFT",
    )
    assert body["prescriber_id"] == str(clinic.verifier.user_id)
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.modify")
    assert event["result"] == "SUCCESS"
    assert event["payload"] == {
        "patient_id": str(clinic.patient_id),
        "changed_fields": ["dose_instruction", "prescriber_id", "repeats"],
    }
    assert "1 mL" not in str(event)
    # An edit is not a transition: the history still holds the one staging row.
    assert rx.events(staged["id"]) == [(None, "DRAFT")]


def test_a_draft_is_cancelled_with_its_reason_on_the_row_the_history_and_the_trail(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    response = rx.client.post(
        f"{URL}/{staged['id']}/cancel",
        json={"reason_code": "PATIENT_DECLINED"},
        headers=clinic.owner.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "CANCELLED"
    assert response.json()["cancel_reason_code"] == "PATIENT_DECLINED"
    assert rx.events(staged["id"]) == [(None, "DRAFT"), ("DRAFT", "CANCELLED")]
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.reject")
    assert (event["result"], event["reason"]) == ("SUCCESS", "PATIENT_DECLINED")
    assert event["payload"] == {
        "patient_id": str(clinic.patient_id),
        "from_state": "DRAFT",
    }


def test_a_signed_script_is_amended_by_a_new_version_and_the_original_is_unchanged(
    rx: RxApi, clinic: Clinic
) -> None:
    signed = _signed(rx, clinic)
    before = rx.row(signed["id"])

    created = _addendum(
        rx,
        clinic.owner.headers,
        signed["id"],
        repeats=0,
        dose_instruction="0.25 mL nocte",
    )
    assert created.status_code == 201, created.text
    version = created.json()
    assert version["state"] == "DRAFT"
    assert version["supersedes_id"] == signed["id"]
    assert (version["repeats"], version["dose_instruction"]) == (0, "0.25 mL nocte")
    assert version["medicine_name"] == signed["medicine_name"]
    assert version["prescriber_id"] == signed["prescriber_id"]

    after = rx.row(signed["id"])
    assert after["state"] == "CANCELLED"
    assert after["cancel_reason_code"] == "SUPERSEDED_BY_ADDENDUM"
    for column in (
        "payload_hash",
        "signed_at",
        "signed_by",
        "dose_instruction",
        "repeats",
        "approval_id",
    ):
        assert after[column] == before[column], column

    # The same key replays the same addendum; another key is refused.
    replay = _addendum(
        rx,
        clinic.owner.headers,
        signed["id"],
        repeats=0,
        dose_instruction="0.25 mL nocte",
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == version["id"]
    other = _addendum(rx, clinic.owner.headers, signed["id"], key="fix-2")
    assert other.status_code == 409
    assert code(other) == "ALREADY_SUPERSEDED"

    # The new version is signed through the gate like any script.
    assert rx.sign_raw(clinic.owner, version["id"]).status_code == 200

    assert clinic.owner.tenant_id is not None
    [modify] = [
        e
        for e in rx.audit(clinic.owner.tenant_id, "prescription.modify")
        if e["result"] == "SUCCESS"
    ]
    assert modify["resource_id"] == uuid.UUID(version["id"])
    assert modify["payload"] == {
        "patient_id": str(clinic.patient_id),
        "changed_fields": ["dose_instruction", "repeats"],
        "supersedes_id": signed["id"],
    }
    [retired] = rx.audit(clinic.owner.tenant_id, "prescription.reject")
    assert retired["reason"] == "SUPERSEDED_BY_ADDENDUM"


def test_the_single_read_and_the_history_are_audited_reads(
    rx: RxApi, clinic: Clinic
) -> None:
    signed = _signed(rx, clinic)
    read = rx.client.get(f"{URL}/{signed['id']}", headers=clinic.owner.headers)
    assert read.status_code == 200
    assert read.json()["state"] == "SIGNED"
    rx.client.post(
        f"{URL}/{signed['id']}/addendum",
        json={"repeats": 1},
        headers={**clinic.owner.headers, "Idempotency-Key": "h"},
    )
    history = rx.client.get(
        f"{URL}/{signed['id']}/history", headers=clinic.owner.headers
    )
    assert history.status_code == 200, history.text
    body = history.json()
    assert [(e["from_state"], e["to_state"]) for e in body["data"]] == [
        (None, "DRAFT"),
        ("DRAFT", "SIGNED"),
        ("SIGNED", "CANCELLED"),
    ]
    assert body["data"][-1]["reason"] == "SUPERSEDED_BY_ADDENDUM"
    assert body["data"][0]["actor_name"] == "Practice Owner"
    assert body["superseded_by_id"] is not None
    assert clinic.owner.tenant_id is not None
    reads = [
        e
        for e in rx.audit(clinic.owner.tenant_id, "prescription.read")
        if e["resource_id"] == uuid.UUID(signed["id"])
    ]
    assert [e["payload"].get("query_filters") for e in reads] == [None, ["history"]]
    assert {e["payload"]["purpose"] for e in reads} == {"PRACTICE_ADMINISTRATION"}


def test_on_the_care_team_a_doctor_edits_their_own_draft(
    rx: RxApi, clinic: Clinic
) -> None:
    doctor = rx.related_member(clinic, "DOCTOR")
    staged = rx.stage(clinic, doctor)
    response = rx.client.patch(
        f"{URL}/{staged['id']}", json={"repeats": 0}, headers=doctor.headers
    )
    assert response.status_code == 200, response.text
    assert (
        rx.client.get(f"{URL}/{staged['id']}", headers=doctor.headers).status_code
        == 200
    )


# -- the database's own refusals --------------------------------------------------------------------


def test_the_database_freezes_the_addendum_link_and_the_cancel_reason(
    rx: RxApi, clinic: Clinic
) -> None:
    staged = rx.stage(clinic)
    with pytest.raises(DBAPIError, match="cancel_reason"), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE prescriptions SET cancel_reason_code = 'DUPLICATE' WHERE id = :id"
            ),
            {"id": uuid.UUID(staged["id"])},
        )
    signed = _signed(rx, clinic)
    version = _addendum(rx, clinic.owner.headers, signed["id"]).json()
    with pytest.raises(DBAPIError, match="SIGNED_IS_IMMUTABLE"), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE prescriptions SET supersedes_id = NULL, addendum_key = NULL WHERE id = :id"
            ),
            {"id": uuid.UUID(version["id"])},
        )
    with pytest.raises(DBAPIError, match="SIGNED_IS_IMMUTABLE"), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE prescriptions SET cancel_reason_code = 'DUPLICATE' WHERE id = :id"
            ),
            {"id": uuid.UUID(signed["id"])},
        )
