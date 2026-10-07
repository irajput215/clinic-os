"""The outbox drain and reconciliation - the minimal worker the dispatch design requires.

`docs/features/10-prescription-safety-gate/03-design.md` "Reconciliation" and
`docs/features/13-integration-boundaries/03-design.md` "Timeout semantics". No new infrastructure: a
function per job, run in process or from the command line, with an **explicit tenant** (FEAT-10 R15:
*"a job without tenant context fails loudly rather than running unscoped"*)::

    cd backend && uv run python -m app.modules.prescriptions.outbox drain --tenant-id <uuid>
    cd backend && uv run python -m app.modules.prescriptions.outbox reconcile --tenant-id <uuid>

**With no transport configured - which is the only configuration that exists - both commands change
nothing and exit `2`** with the count of rows still waiting, so an operator script can never read a
no-op as success.

## The drain, step by step, and why each step is where it is

1. **Claim** a `QUEUED`, never-claimed row `FOR UPDATE SKIP LOCKED` (two drains never take one row),
   re-run the gate on it with the approval rows locked, and either fail it (the approval no longer
   covers it: the prescription goes `QUEUED -> FAILED`, nothing is sent) or stamp `claimed_at`. Commit.
   A row is claimed **before** it is sent, so a crash after sending leaves a claimed, unresolved row,
   which only reconciliation touches - the drain never sends a claimed row again.
2. **Send** once, outside any transaction, with the server-computed idempotency key.
3. **Record** the outcome in a new transaction: `Confirmed -> DISPATCHED`, `Rejected`/`NotSent ->
   FAILED`, `ExplicitUnknown -> REQUIRES_RECONCILIATION` (never success, never failure), with
   `prescription.dispatch` / `prescription.dispatch_failed` and one `integration.request`.

Reconciliation asks the transport about every `REQUIRES_RECONCILIATION` row and every row claimed more
than 60 seconds ago and still `QUEUED`, by key **and** provider reference, and resolves it in either
direction with `resolution_reason = RECONCILED`. A row the provider still cannot answer for stays put.
"""

import argparse
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.core.db import TenantContextRequired, tenant_transaction
from app.modules.audit import service as audit
from app.modules.prescriptions import gate
from app.modules.prescriptions.models import (
    DispatchAttempt,
    Prescription,
    PrescriptionEvent,
)
from app.modules.prescriptions.transport import (
    Confirmed,
    DispatchRequest,
    DispatchTransport,
    ExplicitUnknown,
    NotSent,
    Rejected,
    TransportOutcome,
    configured_transport,
)

# The role the outbox writes its audit events under: there is no human actor.
SYSTEM_ROLE: Final[str] = "SYSTEM_OUTBOX"
# FEAT-13 "Adapter contract": 20 s user-facing, 60 s background. The drain is background.
DEADLINE_SECONDS: Final[float] = 60.0
# FEAT-10 "Reconciliation": rows older than 60 seconds.
RECONCILE_AFTER: Final[timedelta] = timedelta(seconds=60)
EXIT_NO_TRANSPORT: Final[int] = 2


@dataclass
class RunReport:
    """What one run did, in counts only (no identifier, no clinical value)."""

    sent: int = 0
    dispatched: int = 0
    failed: int = 0
    unknown: int = 0
    gate_refused: int = 0
    still_waiting: int = 0
    notes: list[str] = field(default_factory=list)


def _db_now(session: Session) -> datetime:
    """The database clock: every outcome timestamp is read from one clock, not an instance's."""
    value = session.exec(select(func.now())).one()
    assert isinstance(value, datetime)
    return value


def _require_tenant(tenant_id: uuid.UUID | None) -> uuid.UUID:
    if tenant_id is None:
        raise TenantContextRequired(
            "the outbox runs per tenant; refusing to run without explicit tenant context"
        )
    return tenant_id


def _event(
    session: Session,
    *,
    action: str,
    result: str,
    resource_id: uuid.UUID,
    reason: str | None,
    payload: dict[str, object],
) -> None:
    audit.record(
        session,
        audit.AuditEvent(
            action=action,
            result=result,
            resource_id=resource_id,
            reason=reason,
            payload=payload,
        ),
    )


def _move(
    session: Session, row: Prescription, to_state: str, reason: str | None
) -> None:
    previous = row.state
    row.state = to_state
    session.add(row)
    session.flush()
    session.add(
        PrescriptionEvent(
            tenant_id=row.tenant_id,
            prescription_id=row.id,
            from_state=previous,
            to_state=to_state,
            reason=reason,
            actor_id=None,
        )
    )
    session.flush()


def _request(row: Prescription, attempt: DispatchAttempt) -> DispatchRequest:
    return DispatchRequest(
        prescription_id=row.id,
        tenant_id=row.tenant_id,
        patient_id=row.patient_id,
        prescriber_id=row.prescriber_id,
        approval_id=attempt.approval_id,
        medicine_name=row.medicine_name,
        tga_category=row.tga_category,
        dosage_form=row.dosage_form,
        dose_instruction=row.dose_instruction,
        quantity=row.quantity,
        repeats=row.repeats,
        date_of_service=row.date_of_service,
    )


def _waiting(session: Session, tenant_id: uuid.UUID) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(DispatchAttempt)
            .where(
                DispatchAttempt.tenant_id == tenant_id,
                col(DispatchAttempt.state).in_(["QUEUED", "REQUIRES_RECONCILIATION"]),
            )
        ).one()
    )


def _claim(
    tenant_id: uuid.UUID, report: RunReport, limit: int
) -> list[tuple[uuid.UUID, DispatchRequest, str]]:
    """Step 1: claim never-claimed rows, re-checking the gate on each with the approvals locked."""
    claimed: list[tuple[uuid.UUID, DispatchRequest, str]] = []
    with tenant_transaction(tenant_id=tenant_id, actor_role=SYSTEM_ROLE) as session:
        attempts: Sequence[DispatchAttempt] = session.exec(
            select(DispatchAttempt)
            .where(
                DispatchAttempt.tenant_id == tenant_id,
                DispatchAttempt.state == "QUEUED",
                col(DispatchAttempt.claimed_at).is_(None),
            )
            .order_by(col(DispatchAttempt.requested_at))
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for attempt in attempts:
            row = session.exec(
                select(Prescription)
                .where(
                    Prescription.tenant_id == tenant_id,
                    Prescription.id == attempt.prescription_id,
                )
                .with_for_update()
            ).one()
            decision = gate.decide(session, row)
            if not decision.allowed:
                # The approval was revoked, superseded or expired for this date after queueing.
                # Fail closed: nothing is sent, and the prescriber re-dispatches once covered.
                attempt.state = "FAILED"
                attempt.outcome_class = "REJECTED"
                attempt.error_class = decision.reason_code
                attempt.resolution_reason = "GATE_REFUSED_BEFORE_SEND"
                attempt.resolved_at = _db_now(session)
                session.add(attempt)
                _move(session, row, "FAILED", decision.reason_code)
                _event(
                    session,
                    action="prescription.dispatch_failed",
                    result="FAILED",
                    resource_id=row.id,
                    reason=decision.reason_code,
                    payload={"block_reason": decision.reason_code},
                )
                report.gate_refused += 1
                continue
            attempt.claimed_at = _db_now(session)
            session.add(attempt)
            claimed.append(
                (attempt.id, _request(row, attempt), attempt.idempotency_key)
            )
    return claimed


def _resolve(
    tenant_id: uuid.UUID,
    attempt_id: uuid.UUID,
    outcome: TransportOutcome,
    *,
    provider: str,
    latency_ms: int | None,
    reconciled: bool,
    report: RunReport,
) -> None:
    """Step 3: record one outcome. A row already resolved by someone else is left alone."""
    with tenant_transaction(tenant_id=tenant_id, actor_role=SYSTEM_ROLE) as session:
        attempt = session.exec(
            select(DispatchAttempt)
            .where(
                DispatchAttempt.tenant_id == tenant_id, DispatchAttempt.id == attempt_id
            )
            .with_for_update()
        ).one()
        if attempt.state not in ("QUEUED", "REQUIRES_RECONCILIATION"):
            return
        row = session.exec(
            select(Prescription)
            .where(
                Prescription.tenant_id == tenant_id,
                Prescription.id == attempt.prescription_id,
            )
            .with_for_update()
        ).one()
        reason = "RECONCILED" if reconciled else None
        attempt.provider = provider
        attempt.latency_ms = latency_ms
        if isinstance(outcome, Confirmed):
            attempt.state = "DISPATCHED"
            attempt.outcome_class = "CONFIRMED"
            attempt.provider_reference = outcome.provider_reference
            attempt.resolution_reason = reason or "PROVIDER_CONFIRMED"
            attempt.resolved_at = _db_now(session)
            _move(session, row, "DISPATCHED", attempt.resolution_reason)
            _event(
                session,
                action="prescription.dispatch",
                result="SUCCESS",
                resource_id=row.id,
                reason=attempt.resolution_reason,
                payload={
                    "approval_id": str(attempt.approval_id),
                    "idempotency_key": attempt.idempotency_key,
                    "provider": provider,
                },
            )
            report.dispatched += 1
            outcome_class = "CONFIRMED"
        elif isinstance(outcome, Rejected | NotSent):
            attempt.state = "FAILED"
            attempt.outcome_class = "REJECTED"
            attempt.error_class = outcome.error_class
            attempt.resolution_reason = reason or (
                "PROVIDER_REJECTED" if isinstance(outcome, Rejected) else "NOT_SENT"
            )
            attempt.resolved_at = _db_now(session)
            _move(session, row, "FAILED", attempt.resolution_reason)
            _event(
                session,
                action="prescription.dispatch_failed",
                result="FAILED",
                resource_id=row.id,
                reason=attempt.resolution_reason,
                payload={
                    "error_class": outcome.error_class,
                    "outcome_class": "REJECTED",
                    "provider": provider,
                },
            )
            report.failed += 1
            outcome_class = "REJECTED"
        else:
            # ExplicitUnknown: the honest answer is "we do not know". Never success, never failure.
            attempt.error_class = outcome.error_class
            if attempt.state == "QUEUED":
                attempt.state = "REQUIRES_RECONCILIATION"
                attempt.outcome_class = "UNKNOWN"
                _move(session, row, "REQUIRES_RECONCILIATION", outcome.error_class)
                _event(
                    session,
                    action="prescription.dispatch_failed",
                    result="UNKNOWN",
                    resource_id=row.id,
                    reason="UNKNOWN",
                    payload={
                        "error_class": outcome.error_class,
                        "outcome_class": "UNKNOWN",
                        "provider": provider,
                    },
                )
            report.unknown += 1
            outcome_class = "UNKNOWN"
        session.add(attempt)
        _event(
            session,
            action="integration.request",
            result="SUCCESS"
            if outcome_class == "CONFIRMED"
            else ("UNKNOWN" if outcome_class == "UNKNOWN" else "FAILED"),
            resource_id=row.id,
            reason=reason,
            payload={
                "provider": provider,
                "outcome_class": outcome_class,
                **({} if latency_ms is None else {"latency_ms": latency_ms}),
            },
        )


def drain(
    tenant_id: uuid.UUID | None,
    transport: DispatchTransport | None,
    *,
    limit: int = 20,
) -> RunReport:
    """Send what is queued for one tenant. With no transport, change nothing and say so."""
    tenant = _require_tenant(tenant_id)
    report = RunReport()
    if transport is None:
        with tenant_transaction(tenant_id=tenant, actor_role=SYSTEM_ROLE) as session:
            report.still_waiting = _waiting(session, tenant)
        report.notes.append("no transport configured: nothing was sent")
        return report
    for attempt_id, request, key in _claim(tenant, report, limit):
        started = time.monotonic()
        outcome = transport.send(
            request, idempotency_key=key, deadline_seconds=DEADLINE_SECONDS
        )
        report.sent += 1
        _resolve(
            tenant,
            attempt_id,
            outcome,
            provider=transport.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
            reconciled=False,
            report=report,
        )
    with tenant_transaction(tenant_id=tenant, actor_role=SYSTEM_ROLE) as session:
        report.still_waiting = _waiting(session, tenant)
    return report


def reconcile(
    tenant_id: uuid.UUID | None, transport: DispatchTransport | None
) -> RunReport:
    """Resolve every unknown or stale-claimed row by asking the provider, in both directions."""
    tenant = _require_tenant(tenant_id)
    report = RunReport()
    with tenant_transaction(tenant_id=tenant, actor_role=SYSTEM_ROLE) as session:
        if transport is None:
            report.still_waiting = _waiting(session, tenant)
            report.notes.append("no transport configured: nothing was reconciled")
            return report
        stale_before = _db_now(session) - RECONCILE_AFTER
        candidates = [
            (attempt.id, attempt.idempotency_key, attempt.provider_reference)
            for attempt in session.exec(
                select(DispatchAttempt).where(
                    DispatchAttempt.tenant_id == tenant,
                    or_(
                        col(DispatchAttempt.state) == "REQUIRES_RECONCILIATION",
                        and_(
                            col(DispatchAttempt.state) == "QUEUED",
                            col(DispatchAttempt.claimed_at).is_not(None),
                            col(DispatchAttempt.claimed_at) < stale_before,
                        ),
                    ),
                )
            ).all()
        ]
    for attempt_id, key, reference in candidates:
        outcome = transport.lookup(idempotency_key=key, provider_reference=reference)
        _resolve(
            tenant,
            attempt_id,
            outcome,
            provider=transport.provider,
            latency_ms=None,
            reconciled=not isinstance(outcome, ExplicitUnknown),
            report=report,
        )
    with tenant_transaction(tenant_id=tenant, actor_role=SYSTEM_ROLE) as session:
        report.still_waiting = _waiting(session, tenant)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.prescriptions.outbox")
    parser.add_argument("job", choices=("drain", "reconcile"))
    parser.add_argument("--tenant-id", type=uuid.UUID, required=True)
    args = parser.parse_args(argv)
    transport = configured_transport()
    if args.job == "drain":
        report = drain(args.tenant_id, transport)
    else:
        report = reconcile(args.tenant_id, transport)
    # Counts only: no identifier and no clinical value reaches the terminal.
    sys.stdout.write(
        f"{args.job}: sent={report.sent} dispatched={report.dispatched} failed={report.failed}"
        f" unknown={report.unknown} gate_refused={report.gate_refused}"
        f" still_waiting={report.still_waiting} {'; '.join(report.notes)}".rstrip()
        + "\n"
    )
    return EXIT_NO_TRANSPORT if transport is None else 0


if __name__ == "__main__":  # pragma: no cover - the command-line entry point
    sys.exit(main())
