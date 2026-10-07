"""A revocation racing a signature can never leave a signed script without a covering approval.

FEAT-10 R16 / T-10.13 / S14 and FEAT-11 R6. The interleavings are forced, not hoped for: one side
holds its lock in an open transaction while the other is started on a thread, and the test asserts the
second side is *blocked* before letting the first commit. Both orders are exercised, plus two
concurrent signatures of one draft.
"""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.modules.prescriptions import gate, service
from app.modules.prescriptions.service import Refusal
from app.modules.tga_approvals import service as tga_service
from tests.prescriptions.conftest import Clinic, RxApi

# How long a thread must stay blocked for the test to conclude it is waiting on the lock.
_BLOCKED_FOR = 0.6


def _run(target: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def body() -> None:
        try:
            box["result"] = target()
        except BaseException as error:  # pragma: no cover - surfaced by the assertion below
            box["error"] = error

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread, box


def _sign(rx: RxApi, clinic: Clinic, prescription_id: str, token: str) -> Any:
    assert clinic.owner.tenant_id is not None
    return service.sign(
        tenant_id=clinic.owner.tenant_id,
        actor_id=clinic.owner.user_id,
        actor_role="PRACTICE_OWNER",
        prescription_id=uuid.UUID(prescription_id),
        step_up_token=token,
    )


def test_a_revocation_that_holds_the_row_first_blocks_the_signature(
    rx: RxApi, clinic: Clinic
) -> None:
    """Revoke first: the sign waits on the approval row, then sees `REVOKED` and refuses."""
    approval = rx.approve(clinic)
    staged = rx.stage(clinic)
    token = rx.step_up(clinic.owner, staged["id"])

    with engine.connect() as conn, conn.begin():
        conn.execute(
            text(
                "UPDATE tga_approvals SET state = 'REVOKED', revoked_reason_code = 'CLINICAL_ERROR',"
                " revoked_at = now(), revoked_by = :actor WHERE id = :id"
            ),
            {"id": uuid.UUID(approval["id"]), "actor": clinic.owner.user_id},
        )
        thread, box = _run(lambda: _sign(rx, clinic, staged["id"], token))
        time.sleep(_BLOCKED_FOR)
        assert thread.is_alive(), "the signature did not wait for the revocation's row lock"
        # The revocation commits when the block exits.
    thread.join(timeout=10)
    assert "error" not in box, box.get("error")
    result = box["result"]
    assert isinstance(result, Refusal)
    assert result.code == "TGA_APPROVAL_REVOKED"
    row = rx.row(staged["id"])
    assert row["state"] == "DRAFT" and row["signed_at"] is None


def test_a_signature_that_holds_the_row_first_commits_before_the_revocation(
    rx: RxApi, clinic: Clinic, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sign first: the revocation waits until the signature commits, so the approval covered the
    signature at the instant it was taken. The dispatch afterwards is then refused by the gate."""
    approval = rx.approve(clinic)
    staged = rx.stage(clinic)
    token = rx.step_up(clinic.owner, staged["id"])
    decided = threading.Event()
    release = threading.Event()
    real_decide = gate.decide

    def paused_decide(session: Any, prescription: Any) -> gate.GateDecision:
        decision = real_decide(session, prescription)
        decided.set()
        assert release.wait(timeout=10)
        return decision

    monkeypatch.setattr(gate, "decide", paused_decide)
    signer, sign_box = _run(lambda: _sign(rx, clinic, staged["id"], token))
    assert decided.wait(timeout=10)

    assert clinic.owner.tenant_id is not None
    tenant_id = clinic.owner.tenant_id
    revoker, revoke_box = _run(
        lambda: tga_service.revoke_approval(
            tenant_id=tenant_id,
            actor_id=clinic.owner.user_id,
            approval_id=uuid.UUID(approval["id"]),
            reason_code="CLINICAL_ERROR",
        )
    )
    time.sleep(_BLOCKED_FOR)
    assert revoker.is_alive(), "the revocation did not wait for the gate's row lock"
    release.set()
    signer.join(timeout=10)
    revoker.join(timeout=10)
    assert "error" not in sign_box, sign_box.get("error")
    assert "error" not in revoke_box, revoke_box.get("error")
    assert not isinstance(sign_box["result"], Refusal)
    assert rx.row(staged["id"])["state"] == "SIGNED"
    assert rx.tga.row(approval["id"])["state"] == "REVOKED"  # type: ignore[index]

    monkeypatch.setattr(gate, "decide", real_decide)
    blocked = rx.dispatch_raw(clinic.owner, staged["id"])
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "TGA_APPROVAL_REVOKED"
    assert rx.row(staged["id"])["state"] == "BLOCKED"
    assert rx.attempts(staged["id"]) == []


def test_two_concurrent_signatures_produce_one_signed_row(rx: RxApi, clinic: Clinic) -> None:
    """FEAT-11 R6: exactly one `SIGNED` row and one successful `prescription.sign`."""
    rx.approve(clinic)
    staged = rx.stage(clinic)
    tokens = [rx.step_up(clinic.owner, staged["id"]) for _ in range(2)]
    runs = [_run(lambda t=token: _sign(rx, clinic, staged["id"], t)) for token in tokens]
    for thread, _box in runs:
        thread.join(timeout=10)
    results = [box["result"] for _thread, box in runs]
    refusals = [r for r in results if isinstance(r, Refusal)]
    assert len(refusals) == 1 and refusals[0].code == "INVALID_STATE_TRANSITION"
    assert clinic.owner.tenant_id is not None
    signed = [
        e for e in rx.audit(clinic.owner.tenant_id, "prescription.sign") if e["result"] == "SUCCESS"
    ]
    assert len(signed) == 1
