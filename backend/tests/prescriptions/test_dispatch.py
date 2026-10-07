"""Dispatch: Idempotency-Key, the gate re-run, the transactional outbox (FEAT-10 R5-R13)."""

import hashlib

import pytest

from tests.prescriptions.conftest import URL, Clinic, RxApi, code


def _signed(rx: RxApi, clinic: Clinic) -> str:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    assert rx.sign_raw(clinic.owner, staged["id"]).status_code == 200
    return str(staged["id"])


def test_a_nurse_cannot_dispatch(rx: RxApi, clinic: Clinic) -> None:
    prescription_id = _signed(rx, clinic)
    nurse = rx.member(clinic, "NURSE")
    response = rx.client.post(
        f"{URL}/{prescription_id}/dispatch",
        json={"step_up_token": "x" * 43},
        headers={**nurse.headers, "Idempotency-Key": "k"},
    )
    assert response.status_code == 403
    assert code(response) == "PERMISSION_NOT_HELD"


@pytest.mark.parametrize("key", [None, "", "   ", "x" * 256, "bad\nkey"])
def test_dispatch_requires_an_idempotency_key(rx: RxApi, clinic: Clinic, key: str | None) -> None:
    prescription_id = _signed(rx, clinic)
    response = rx.dispatch_raw(clinic.owner, prescription_id, key=key, token="x" * 43)
    assert response.status_code == 422
    assert code(response) == "IDEMPOTENCY_KEY_REQUIRED"
    assert rx.attempts(prescription_id) == []


def test_a_draft_cannot_be_dispatched(rx: RxApi, clinic: Clinic) -> None:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    response = rx.dispatch_raw(clinic.owner, staged["id"])
    assert response.status_code == 409
    assert code(response) == "INVALID_STATE_TRANSITION"
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.dispatch_blocked")
    assert event["payload"] == {"block_reason": "STATE_INVALID"}


def test_dispatch_needs_its_own_step_up(rx: RxApi, clinic: Clinic) -> None:
    prescription_id = _signed(rx, clinic)
    sign_grant = rx.step_up(clinic.owner, prescription_id, "prescription.sign")
    response = rx.dispatch_raw(clinic.owner, prescription_id, token=sign_grant)
    assert response.status_code == 403
    assert code(response) == "STEP_UP_REQUIRED"
    assert rx.row(prescription_id)["state"] == "SIGNED"


def test_a_covered_dispatch_is_queued_in_the_outbox_and_never_reported_sent(
    rx: RxApi, clinic: Clinic
) -> None:
    prescription_id = _signed(rx, clinic)
    response = rx.dispatch_raw(clinic.owner, prescription_id, key="client-intent-7")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "QUEUED"
    assert body["gate"] is None
    assert body["dispatch"]["state"] == "QUEUED"
    assert body["dispatch"]["provider"] is None
    assert body["dispatch"]["transport_configured"] is False
    [attempt] = rx.attempts(prescription_id)
    assert attempt["attempt_seq"] == 1
    assert attempt["claimed_at"] is None
    # R12: the client's header is hashed with the tenant and prescription, never stored raw.
    expected = hashlib.sha256(
        f"{clinic.owner.tenant_id}:{prescription_id}:client-intent-7".encode()
    ).hexdigest()
    assert attempt["idempotency_key"] == expected
    assert rx.events(prescription_id)[-1] == ("SIGNED", "QUEUED")
    assert clinic.owner.tenant_id is not None
    [event] = rx.audit(clinic.owner.tenant_id, "prescription.dispatch")
    assert event["result"] == "SUCCESS"
    assert event["payload"]["idempotency_key"] == expected
    assert "client-intent-7" not in str(event)


def test_a_retry_with_the_same_key_returns_the_first_result(rx: RxApi, clinic: Clinic) -> None:
    """S5 / US-3: one outbox row, one `prescription.dispatch` event; the replay answers `200`."""
    prescription_id = _signed(rx, clinic)
    first = rx.dispatch_raw(clinic.owner, prescription_id, key="same")
    assert first.status_code == 202
    # A retry after the grant was spent: the replay needs no new step-up and changes nothing.
    replay = rx.dispatch_raw(clinic.owner, prescription_id, key="same", token="y" * 43)
    assert replay.status_code == 200
    assert replay.json()["state"] == "QUEUED"
    assert len(rx.attempts(prescription_id)) == 1
    assert clinic.owner.tenant_id is not None
    assert len(rx.audit(clinic.owner.tenant_id, "prescription.dispatch")) == 1


def test_a_second_intent_cannot_double_dispatch(rx: RxApi, clinic: Clinic) -> None:
    prescription_id = _signed(rx, clinic)
    assert rx.dispatch_raw(clinic.owner, prescription_id, key="one").status_code == 202
    second = rx.dispatch_raw(clinic.owner, prescription_id, key="two")
    assert second.status_code == 409
    assert len(rx.attempts(prescription_id)) == 1
    assert clinic.owner.tenant_id is not None
    blocked = rx.audit(clinic.owner.tenant_id, "prescription.dispatch_blocked")
    assert blocked[-1]["payload"] == {"block_reason": "ALREADY_DISPATCHED"}


def test_a_revoked_approval_blocks_dispatch_and_a_new_one_releases_it_without_re_signing(
    rx: RxApi, clinic: Clinic
) -> None:
    """R5 at dispatch, FEAT-11 R10: `BLOCKED`, nothing queued; then `QUEUED` with no new signature."""
    rx.approve(clinic, reference="TGA-FIRST-01")
    staged = rx.stage(clinic)
    assert rx.sign_raw(clinic.owner, staged["id"]).status_code == 200
    [approval] = rx.tga.list_for_patient(clinic.owner, clinic.patient_id).json()["data"]
    assert rx.tga.revoke(clinic.owner, approval["id"]).status_code == 200

    blocked = rx.dispatch_raw(clinic.owner, staged["id"], key="a")
    assert blocked.status_code == 422
    assert code(blocked) == "TGA_APPROVAL_REVOKED"
    assert rx.row(staged["id"])["state"] == "BLOCKED"
    assert rx.attempts(staged["id"]) == []
    again = rx.dispatch_raw(clinic.owner, staged["id"], key="b")
    assert code(again) == "TGA_APPROVAL_REVOKED"
    assert clinic.owner.tenant_id is not None
    events = rx.audit(clinic.owner.tenant_id, "prescription.dispatch_blocked")
    assert [e["payload"]["block_reason"] for e in events] == ["TGA_APPROVAL_REVOKED"] * 2

    renewed = rx.approve(clinic, reference="TGA-RENEW-02")
    released = rx.dispatch_raw(clinic.owner, staged["id"], key="c")
    assert released.status_code == 202
    assert released.json()["approval_id"] == renewed["id"]
    assert len(rx.audit(clinic.owner.tenant_id, "prescription.sign")) == 1
    assert rx.events(staged["id"])[-2:] == [("SIGNED", "BLOCKED"), ("BLOCKED", "QUEUED")]


def test_another_tenants_prescription_cannot_be_dispatched(rx: RxApi, clinic: Clinic) -> None:
    other = rx.clinic("Other Clinic")
    foreign = rx.stage(other)
    response = rx.client.post(
        f"{URL}/{foreign['id']}/dispatch",
        json={"step_up_token": "x" * 43},
        headers={**clinic.owner.headers, "Idempotency-Key": "k"},
    )
    assert response.status_code == 404
