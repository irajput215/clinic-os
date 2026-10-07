"""The outbox drain and reconciliation, against a simulated transport (FEAT-13 "CI driver").

With no transport configured - production today - nothing is ever sent and nothing is reported sent.
With the simulated driver: confirmed, rejected, unknown, reconciled both ways, never duplicated, and
the gate re-checked before anything leaves.
"""

import uuid
from dataclasses import dataclass, field

import pytest

from app.core.db import TenantContextRequired
from app.modules.prescriptions import outbox
from app.modules.prescriptions.transport import (
    Confirmed,
    DispatchRequest,
    ExplicitUnknown,
    NotSent,
    Rejected,
    TransportOutcome,
    configured_transport,
)
from tests.prescriptions.conftest import Clinic, RxApi


@dataclass
class SimulatedTransport:
    """Scripted outcomes; records every call. Lives in the tests, so no deployment can select it."""

    send_outcome: TransportOutcome = field(default_factory=lambda: Confirmed("EVQ-REF-1"))
    lookup_outcome: TransportOutcome = field(default_factory=lambda: ExplicitUnknown("TIMEOUT"))
    sent: list[tuple[DispatchRequest, str]] = field(default_factory=list)
    looked_up: list[str] = field(default_factory=list)

    @property
    def provider(self) -> str:
        return "simulated"

    def send(
        self, request: DispatchRequest, *, idempotency_key: str, deadline_seconds: float
    ) -> TransportOutcome:
        assert idempotency_key and deadline_seconds > 0
        self.sent.append((request, idempotency_key))
        return self.send_outcome

    def lookup(self, *, idempotency_key: str, provider_reference: str | None) -> TransportOutcome:
        self.looked_up.append(idempotency_key)
        return self.lookup_outcome


def _queued(rx: RxApi, clinic: Clinic) -> str:
    rx.approve(clinic)
    staged = rx.stage(clinic)
    assert rx.sign_raw(clinic.owner, staged["id"]).status_code == 200
    assert rx.dispatch_raw(clinic.owner, staged["id"]).status_code == 202
    return str(staged["id"])


def _tenant(clinic: Clinic) -> uuid.UUID:
    assert clinic.owner.tenant_id is not None
    return clinic.owner.tenant_id


def test_no_transport_is_configured_in_any_deployment() -> None:
    assert configured_transport() is None


def test_the_drain_refuses_to_run_without_a_tenant() -> None:
    """FEAT-10 R15 / S17: fails loudly rather than running unscoped."""
    with pytest.raises(TenantContextRequired):
        outbox.drain(None, SimulatedTransport())
    with pytest.raises(TenantContextRequired):
        outbox.reconcile(None, SimulatedTransport())


def test_without_a_transport_nothing_moves_and_the_command_says_so(
    rx: RxApi, clinic: Clinic, capsys: pytest.CaptureFixture[str]
) -> None:
    prescription_id = _queued(rx, clinic)
    report = outbox.drain(_tenant(clinic), None)
    assert report.sent == 0 and report.still_waiting == 1
    assert outbox.reconcile(_tenant(clinic), None).still_waiting == 1
    assert outbox.main(["drain", "--tenant-id", str(_tenant(clinic))]) == outbox.EXIT_NO_TRANSPORT
    assert "no transport configured" in capsys.readouterr().out
    assert outbox.main(["reconcile", "--tenant-id", str(_tenant(clinic))]) == 2
    assert rx.row(prescription_id)["state"] == "QUEUED"
    [attempt] = rx.attempts(prescription_id)
    assert attempt["state"] == "QUEUED" and attempt["claimed_at"] is None


def test_a_confirmed_send_is_dispatched_once(rx: RxApi, clinic: Clinic) -> None:
    prescription_id = _queued(rx, clinic)
    transport = SimulatedTransport()
    report = outbox.drain(_tenant(clinic), transport)
    assert (report.sent, report.dispatched, report.still_waiting) == (1, 1, 0)
    [(request, key)] = transport.sent
    assert str(request.prescription_id) == prescription_id
    [attempt] = rx.attempts(prescription_id)
    assert key == attempt["idempotency_key"]
    assert (attempt["state"], attempt["provider"], attempt["provider_reference"]) == (
        "DISPATCHED",
        "simulated",
        "EVQ-REF-1",
    )
    assert rx.row(prescription_id)["state"] == "DISPATCHED"
    reasons = [
        e["reason"] for e in rx.audit(_tenant(clinic), "prescription.dispatch")
    ]
    assert reasons == [None, "PROVIDER_CONFIRMED"]
    assert rx.audit(_tenant(clinic), "integration.request")[0]["payload"]["provider"] == "simulated"
    # A second run sends nothing again.
    assert outbox.drain(_tenant(clinic), transport).sent == 0
    assert len(transport.sent) == 1


@pytest.mark.parametrize("outcome", [Rejected("PROVIDER_4XX"), NotSent("CONNECTION_REFUSED")])
def test_a_rejection_or_unsent_request_fails(
    rx: RxApi, clinic: Clinic, outcome: TransportOutcome
) -> None:
    prescription_id = _queued(rx, clinic)
    outbox.drain(_tenant(clinic), SimulatedTransport(send_outcome=outcome))
    assert rx.row(prescription_id)["state"] == "FAILED"
    [event] = rx.audit(_tenant(clinic), "prescription.dispatch_failed")
    assert event["result"] == "FAILED"
    # FAILED may be re-dispatched as a new clinical intent (attempt 2).
    again = rx.dispatch_raw(clinic.owner, prescription_id, key="second-intent")
    assert again.status_code == 202
    assert [a["attempt_seq"] for a in rx.attempts(prescription_id)] == [1, 2]


def test_a_timeout_is_never_success_and_reconciliation_resolves_it(
    rx: RxApi, clinic: Clinic
) -> None:
    """S10, S12, S13, A3: unknown -> `REQUIRES_RECONCILIATION`; resolved once, `RECONCILED`."""
    prescription_id = _queued(rx, clinic)
    transport = SimulatedTransport(send_outcome=ExplicitUnknown("TIMEOUT"))
    report = outbox.drain(_tenant(clinic), transport)
    assert report.unknown == 1 and report.dispatched == 0
    assert rx.row(prescription_id)["state"] == "REQUIRES_RECONCILIATION"
    [unknown] = rx.audit(_tenant(clinic), "prescription.dispatch_failed")
    assert unknown["result"] == "UNKNOWN"

    # The provider still cannot say: nothing changes, nothing is resent.
    still = outbox.reconcile(_tenant(clinic), transport)
    assert still.still_waiting == 1 and len(transport.sent) == 1
    assert rx.row(prescription_id)["state"] == "REQUIRES_RECONCILIATION"

    transport.lookup_outcome = Confirmed("EVQ-LATE-9")
    outbox.reconcile(_tenant(clinic), transport)
    assert rx.row(prescription_id)["state"] == "DISPATCHED"
    [attempt] = rx.attempts(prescription_id)
    assert attempt["resolution_reason"] == "RECONCILED"
    assert rx.audit(_tenant(clinic), "prescription.dispatch")[-1]["reason"] == "RECONCILED"

    # Re-running reconciliation on a resolved row changes nothing and sends nothing.
    assert outbox.reconcile(_tenant(clinic), transport).dispatched == 0
    assert len(transport.sent) == 1


def test_reconciliation_resolves_the_other_direction_too(rx: RxApi, clinic: Clinic) -> None:
    prescription_id = _queued(rx, clinic)
    transport = SimulatedTransport(send_outcome=ExplicitUnknown("MALFORMED_BODY"))
    outbox.drain(_tenant(clinic), transport)
    transport.lookup_outcome = Rejected("NOT_RECEIVED")
    outbox.reconcile(_tenant(clinic), transport)
    assert rx.row(prescription_id)["state"] == "FAILED"
    assert rx.attempts(prescription_id)[0]["resolution_reason"] == "RECONCILED"


def test_the_gate_is_re_checked_before_anything_leaves(rx: RxApi, clinic: Clinic) -> None:
    """A revocation after queueing: the drain fails the row closed and sends nothing."""
    prescription_id = _queued(rx, clinic)
    [approval] = rx.tga.list_for_patient(clinic.owner, clinic.patient_id).json()["data"]
    assert rx.tga.revoke(clinic.owner, approval["id"]).status_code == 200
    transport = SimulatedTransport()
    report = outbox.drain(_tenant(clinic), transport)
    assert report.gate_refused == 1 and transport.sent == []
    assert rx.row(prescription_id)["state"] == "FAILED"
    [attempt] = rx.attempts(prescription_id)
    assert (attempt["state"], attempt["error_class"]) == ("FAILED", "TGA_APPROVAL_REVOKED")


def test_a_claimed_but_unresolved_row_is_never_sent_twice(rx: RxApi, clinic: Clinic) -> None:
    """A crash between sending and recording leaves a claimed row: only reconciliation touches it."""
    prescription_id = _queued(rx, clinic)
    report = outbox.RunReport()
    claimed = outbox._claim(_tenant(clinic), report, limit=10)  # the crash: sent, never recorded
    assert len(claimed) == 1
    transport = SimulatedTransport()
    assert outbox.drain(_tenant(clinic), transport).sent == 0
    assert rx.row(prescription_id)["state"] == "QUEUED"
