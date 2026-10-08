"""The prescriptions service facade - the only place `prescriptions`, `prescription_events` and
`dispatch_attempts` are queried.

Design: `docs/features/11-prescribing/03-design.md` (stage, sign, the state machine),
`docs/features/10-prescription-safety-gate/03-design.md` (the gate, `dispatch_attempts`, idempotency)
and `docs2/sdlc/07-script-queue/api.md` (the four agreed endpoints).

Rules, in the order the designs fix them:

- **Every query runs in `tenant_transaction`** and also carries `tenant_id = :tenant_id`.
- **A refusal is returned, not raised**, so the transaction that carries its `DENIED` audit event
  commits (the same `Refusal` shape the TGA module uses). The router raises it afterwards.
- **Every state change is audited on the same transaction** and appends a `prescription_events` row; a
  failed audit write propagates and rolls the change back (INV-4).
- **The gate decides inside the signing and dispatch transactions** (`gate.decide`), after the
  prescription row is locked `FOR UPDATE` and with the approval rows locked by the gate itself. The
  state the gate authorises commits in that same transaction, so no revocation can interleave.
- **No clinical value reaches an audit payload or a log line**: identifiers, codes and classes only.

The dispatch route writes the outbox row and stops. Sending is `outbox.drain`, which needs a
transport, and none is configured (`transport.configured_transport`): a dispatched prescription is
reported `QUEUED`, never sent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from hmac import compare_digest
from typing import Any, Final

from fastapi import status
from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.identity_tenancy import service as identity
from app.modules.patients import service as patients_service
from app.modules.prescriptions import gate
from app.modules.prescriptions.models import (
    LEGAL_TRANSITIONS,
    DispatchAttempt,
    Prescription,
    PrescriptionEvent,
)
from app.modules.prescriptions.schemas import (
    DispatchRead,
    PrescriberRead,
    PrescribersPublic,
    PrescriptionCreate,
    PrescriptionRead,
    PrescriptionsPublic,
)
from app.modules.prescriptions.transport import configured_transport
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import PRESCRIPTION_PERMISSIONS

# The closed catalogue's actions (`app/modules/audit/actions.py`).
CREATE: Final[str] = "prescription.create"
SIGN: Final[str] = "prescription.sign"
DISPATCH: Final[str] = "prescription.dispatch"
DISPATCH_BLOCKED: Final[str] = "prescription.dispatch_blocked"

# Refusal codes.
NOT_FOUND: Final[str] = "PRESCRIPTION_NOT_FOUND"
CROSS_TENANT: Final[str] = "CROSS_TENANT"
PATIENT_NOT_FOUND: Final[str] = "PATIENT_NOT_FOUND"
PRESCRIBER_NOT_AUTHORIZED: Final[str] = "PRESCRIBER_NOT_AUTHORIZED"
NOT_PRESCRIBER_OF_RECORD: Final[str] = "NOT_PRESCRIBER_OF_RECORD"
INVALID_STATE_TRANSITION: Final[str] = "INVALID_STATE_TRANSITION"
IDEMPOTENCY_KEY_REQUIRED: Final[str] = "IDEMPOTENCY_KEY_REQUIRED"
# FEAT-10's block reasons for the non-gate refusals at dispatch (step 9).
ALREADY_DISPATCHED: Final[str] = "ALREADY_DISPATCHED"
STATE_INVALID: Final[str] = "STATE_INVALID"

# States in which a prescription still needs a human action, so the queue shows the live gate.
ACTIONABLE_STATES: Final[frozenset[str]] = frozenset(
    {"DRAFT", "SIGNED", "BLOCKED", "FAILED"}
)
# States from which `dispatch` may queue (FEAT-11 transitions into `QUEUED`).
DISPATCHABLE_STATES: Final[frozenset[str]] = frozenset({"SIGNED", "BLOCKED", "FAILED"})
_IN_FLIGHT_STATES: Final[frozenset[str]] = frozenset(
    {"QUEUED", "DISPATCHED", "REQUIRES_RECONCILIATION", "REVERSED"}
)

MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_PAGE_SIZE: Final[int] = 50
_CURSOR_CONTEXT: Final[bytes] = b"clinos.prescriptions.cursor.v1"


@dataclass(frozen=True)
class Refusal:
    """A refused operation: the code, the status and the sentence the client is shown."""

    code: str
    status_code: int
    message: str


@dataclass(frozen=True)
class DispatchResult:
    """The prescription after a dispatch, and whether this answer replays an earlier request."""

    prescription: PrescriptionRead
    replayed: bool


class InvalidCursor(RuntimeError):
    """The cursor is malformed or was not signed by this application. The router answers `422`."""


# --------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------


def _record(
    session: Session,
    *,
    action: str,
    result: str,
    resource_id: uuid.UUID | None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
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


def audit_denial(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str | None,
    action: str,
    reason: str,
) -> None:
    """Record a refusal the policy layer made, before any domain transaction opened."""
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        _record(
            session, action=action, result="DENIED", resource_id=None, reason=reason
        )


def _transition(
    session: Session,
    row: Prescription,
    *,
    to_state: str,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
) -> None:
    """Apply one legal transition and append its history row. Callers check legality first."""
    if to_state not in LEGAL_TRANSITIONS[row.state]:
        # Unreachable through the service (each caller refuses first); the trigger refuses it too.
        raise RuntimeError(f"{row.state} -> {to_state} is not a permitted transition")
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
            actor_id=actor_id,
        )
    )
    session.flush()


def _payload_hash(row: Prescription) -> str:
    """SHA-256 over the canonical clinical payload: proof of *what* was signed, never the payload."""
    payload = {
        "patient_id": str(row.patient_id),
        "prescriber_id": str(row.prescriber_id),
        "medicine_name": row.medicine_name,
        "tga_category": row.tga_category,
        "dosage_form": row.dosage_form,
        "dose_instruction": row.dose_instruction,
        "quantity": str(row.quantity),
        "repeats": row.repeats,
        "triage_outcome": row.triage_outcome,
        "conventional_therapy": row.conventional_therapy,
        "date_of_service": row.date_of_service.isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def idempotency_key(
    *, tenant_id: uuid.UUID, prescription_id: uuid.UUID, client_key: str
) -> str:
    """FEAT-10 R12: the client's header is hashed into the key, never stored or used raw.

    Bound to the tenant and the prescription, so one header value can never collide across tenants
    or replay onto a different prescription.
    """
    material = f"{tenant_id}:{prescription_id}:{client_key}".encode()
    return hashlib.sha256(material).hexdigest()


def _lock(
    session: Session, *, tenant_id: uuid.UUID, prescription_id: uuid.UUID
) -> Prescription | None:
    """The row, locked until the transaction ends; `None` for absent **and** another tenant's."""
    return session.exec(
        select(Prescription)
        .where(Prescription.id == prescription_id, Prescription.tenant_id == tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()


def _latest_attempts(
    session: Session, *, tenant_id: uuid.UUID, prescription_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, DispatchAttempt]:
    if not prescription_ids:
        return {}
    rows: Sequence[DispatchAttempt] = session.exec(
        select(DispatchAttempt)
        .where(
            DispatchAttempt.tenant_id == tenant_id,
            col(DispatchAttempt.prescription_id).in_(prescription_ids),
        )
        .order_by(col(DispatchAttempt.attempt_seq))
    ).all()
    return {row.prescription_id: row for row in rows}


def _reads(
    session: Session, *, tenant_id: uuid.UUID, rows: Sequence[Prescription]
) -> list[PrescriptionRead]:
    """Convert rows inside the transaction, with names, the latest dispatch and the live gate."""
    patient_names = patients_service.display_names(
        session, tenant_id=tenant_id, patient_ids=[row.patient_id for row in rows]
    )
    people = users_roles.display_names(
        tenant_id=tenant_id,
        user_ids=[row.prescriber_id for row in rows] + [row.drafted_by for row in rows],
    )
    attempts = _latest_attempts(
        session, tenant_id=tenant_id, prescription_ids=[row.id for row in rows]
    )
    transport_configured = configured_transport() is not None
    reads: list[PrescriptionRead] = []
    for row in rows:
        attempt = attempts.get(row.id)
        reads.append(
            PrescriptionRead(
                id=row.id,
                patient_id=row.patient_id,
                patient_name=patient_names.get(row.patient_id),
                prescriber_id=row.prescriber_id,
                prescriber_name=people.get(row.prescriber_id),
                drafted_by=row.drafted_by,
                drafted_by_name=people.get(row.drafted_by),
                medicine_name=row.medicine_name,
                tga_category=row.tga_category,
                dosage_form=row.dosage_form,
                dose_instruction=row.dose_instruction,
                quantity=row.quantity,
                repeats=row.repeats,
                triage_outcome=row.triage_outcome,
                conventional_therapy=row.conventional_therapy,
                date_of_service=row.date_of_service,
                state=row.state,
                approval_id=row.approval_id,
                created_at=row.created_at,
                signed_at=row.signed_at,
                gate=gate.advise(session, row)
                if row.state in ACTIONABLE_STATES
                else None,
                dispatch=None
                if attempt is None
                else DispatchRead(
                    state=attempt.state,
                    attempt_seq=attempt.attempt_seq,
                    provider=attempt.provider,
                    provider_reference=attempt.provider_reference,
                    outcome_class=attempt.outcome_class,
                    requested_at=attempt.requested_at,
                    resolved_at=attempt.resolved_at,
                    transport_configured=transport_configured,
                ),
            )
        )
    return reads


def _read_one(session: Session, row: Prescription) -> PrescriptionRead:
    session.flush()
    session.refresh(row)
    return _reads(session, tenant_id=row.tenant_id, rows=[row])[0]


# --------------------------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------------------------


def _cursor_signature(payload: bytes) -> str:
    secret = str(settings.SECRET_KEY).encode("utf-8")
    return base64.urlsafe_b64encode(
        hashlib.sha256(_CURSOR_CONTEXT + secret + payload).digest()[:16]
    ).decode("ascii")


def encode_cursor(row: Prescription) -> str:
    payload = json.dumps(
        {"i": str(row.id), "t": row.created_at.isoformat()},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{body}.{_cursor_signature(payload)}"


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        body, signature = cursor.split(".", 1)
        payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (ValueError, TypeError) as error:
        raise InvalidCursor("the cursor is not a cursor this API issued") from error
    if not compare_digest(signature, _cursor_signature(payload)):
        raise InvalidCursor("the cursor signature does not verify")
    try:
        decoded = json.loads(payload)
        return datetime.fromisoformat(str(decoded["t"])), uuid.UUID(str(decoded["i"]))
    except (ValueError, KeyError, TypeError) as error:
        raise InvalidCursor("the cursor does not name a position") from error


def list_prescriptions(
    *,
    tenant_id: uuid.UUID,
    states: Sequence[str] = (),
    prescriber_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> PrescriptionsPublic:
    """One keyset page, newest first. Actionable rows carry the gate as it answers **now** (R2)."""
    decoded = None if cursor is None else decode_cursor(cursor)
    with tenant_transaction(tenant_id=tenant_id) as session:
        conditions = [col(Prescription.tenant_id) == tenant_id]
        if states:
            conditions.append(col(Prescription.state).in_(list(states)))
        if prescriber_id is not None:
            conditions.append(col(Prescription.prescriber_id) == prescriber_id)
        if patient_id is not None:
            conditions.append(col(Prescription.patient_id) == patient_id)
        if decoded is not None:
            created_at, last_id = decoded
            conditions.append(
                or_(
                    col(Prescription.created_at) < created_at,
                    and_(
                        col(Prescription.created_at) == created_at,
                        col(Prescription.id) < last_id,
                    ),
                )
            )
        rows: Sequence[Prescription] = session.exec(
            select(Prescription)
            .where(*conditions)
            .order_by(col(Prescription.created_at).desc(), col(Prescription.id).desc())
            .limit(limit + 1)
        ).all()
        page, overflow = list(rows[:limit]), rows[limit:]
        return PrescriptionsPublic(
            data=_reads(session, tenant_id=tenant_id, rows=page),
            next_cursor=encode_cursor(page[-1]) if overflow else None,
        )


def list_prescribers(*, tenant_id: uuid.UUID) -> PrescribersPublic:
    """The accounts that may sign, by permission (never by role name), sorted by name."""
    holders = users_roles.holders_of(
        tenant_id=tenant_id, permission=PRESCRIPTION_PERMISSIONS["sign"]
    )
    return PrescribersPublic(
        data=[
            PrescriberRead(id=user_id, name=name)
            for user_id, name in sorted(
                holders.items(), key=lambda item: (item[1], item[0])
            )
        ]
    )


# --------------------------------------------------------------------------------------------
# Stage
# --------------------------------------------------------------------------------------------


def stage(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str | None,
    body: PrescriptionCreate,
) -> PrescriptionRead | Refusal:
    """Create a `DRAFT` for a patient of this tenant, addressed to a prescriber who may sign it."""
    patient = patients_service.get_patient(
        tenant_id=tenant_id, patient_id=body.patient_id
    )
    prescribers = users_roles.holders_of(
        tenant_id=tenant_id, permission=PRESCRIPTION_PERMISSIONS["sign"]
    )
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        if patient is None:
            _record(
                session,
                action=CREATE,
                result="DENIED",
                resource_id=None,
                reason=CROSS_TENANT,
            )
            return Refusal(
                PATIENT_NOT_FOUND, status.HTTP_404_NOT_FOUND, "Patient not found"
            )
        if body.prescriber_id not in prescribers:
            _record(
                session,
                action=CREATE,
                result="DENIED",
                resource_id=None,
                reason=PRESCRIBER_NOT_AUTHORIZED,
            )
            return Refusal(
                PRESCRIBER_NOT_AUTHORIZED,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Choose a prescriber in this organisation who may sign prescriptions",
            )
        row = Prescription(
            tenant_id=tenant_id,
            drafted_by=actor_id,
            state="DRAFT",
            **body.model_dump(),
        )
        session.add(row)
        session.flush()
        session.add(
            PrescriptionEvent(
                tenant_id=tenant_id,
                prescription_id=row.id,
                from_state=None,
                to_state="DRAFT",
                actor_id=actor_id,
            )
        )
        _record(
            session,
            action=CREATE,
            result="SUCCESS",
            resource_id=row.id,
            payload={"patient_id": str(row.patient_id)},
        )
        return _read_one(session, row)


# --------------------------------------------------------------------------------------------
# Sign
# --------------------------------------------------------------------------------------------


def sign(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str | None,
    prescription_id: uuid.UUID,
    step_up_token: str,
) -> PrescriptionRead | Refusal:
    """`DRAFT -> SIGNED`, in one transaction: lock, identity, step-up, state, **gate**, write, audit.

    The order is the deny-by-default path. A gate refusal leaves the row `DRAFT` (the state machine
    has no `DRAFT -> BLOCKED`), is answered `422` with the match reason as `detail.code`, and is
    audited as `prescription.sign` `DENIED` with the `block_reason` - the catalogue has no
    `sign_blocked` action, and docs2's proposed `prescription.sign_blocked` name is not invented.
    """
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        row = _lock(session, tenant_id=tenant_id, prescription_id=prescription_id)
        if row is None:
            _record(
                session,
                action=SIGN,
                result="DENIED",
                resource_id=None,
                reason=CROSS_TENANT,
            )
            return Refusal(
                NOT_FOUND, status.HTTP_404_NOT_FOUND, "Prescription not found"
            )
        if row.prescriber_id != actor_id:
            _record(
                session,
                action=SIGN,
                result="DENIED",
                resource_id=row.id,
                reason=NOT_PRESCRIBER_OF_RECORD,
            )
            return Refusal(
                NOT_PRESCRIBER_OF_RECORD,
                status.HTTP_403_FORBIDDEN,
                "Only the prescriber of record can sign this prescription",
            )
        if not identity.consume_step_up(
            session,
            tenant_id=tenant_id,
            user_id=actor_id,
            operation=SIGN,
            resource_id=row.id,
            token=step_up_token,
        ):
            return Refusal(
                identity.STEP_UP_REQUIRED,
                status.HTTP_403_FORBIDDEN,
                "Signing needs a fresh step-up: re-enter your password",
            )
        if row.state != "DRAFT":
            _record(
                session,
                action=SIGN,
                result="DENIED",
                resource_id=row.id,
                reason=INVALID_STATE_TRANSITION,
            )
            return Refusal(
                INVALID_STATE_TRANSITION,
                status.HTTP_409_CONFLICT,
                f"A {row.state} prescription cannot be signed",
            )

        decision = gate.decide(session, row)
        if not decision.allowed:
            _record(
                session,
                action=SIGN,
                result="DENIED",
                resource_id=row.id,
                reason=decision.reason_code,
                payload={
                    "block_reason": decision.reason_code,
                    "patient_id": str(row.patient_id),
                },
            )
            return Refusal(
                decision.reason_code or "TGA_APPROVAL_NOT_FOUND",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                gate.REFUSAL_MESSAGE,
            )

        row.signed_at = session.connection().execute(select(func.now())).scalar_one()
        row.signed_by = actor_id
        row.payload_hash = _payload_hash(row)
        row.approval_id = decision.approval_id
        _transition(session, row, to_state="SIGNED", actor_id=actor_id)
        _record(
            session,
            action=SIGN,
            result="SUCCESS",
            resource_id=row.id,
            payload={
                "patient_id": str(row.patient_id),
                "approval_id": str(decision.approval_id),
                "step_up": True,
            },
        )
        return _read_one(session, row)


# --------------------------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------------------------


def _replay(
    session: Session, *, tenant_id: uuid.UUID, key: str
) -> DispatchAttempt | None:
    return session.exec(
        select(DispatchAttempt).where(
            DispatchAttempt.tenant_id == tenant_id,
            DispatchAttempt.idempotency_key == key,
        )
    ).first()


def dispatch(
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: str | None,
    prescription_id: uuid.UUID,
    step_up_token: str,
    client_key: str,
) -> DispatchResult | Refusal:
    """`SIGNED | BLOCKED | FAILED -> QUEUED` and the outbox row, or `-> BLOCKED`, in one transaction.

    1. Lock the prescription. Absent or another tenant's: `404`.
    2. Idempotency: the server-computed key already names an attempt -> the original result,
       unchanged, with no second gate run, no second outbox row and no step-up spent (FEAT-10 R11).
    3. Step-up for `prescription.dispatch` on this prescription, spent once.
    4. State: only `SIGNED`, `BLOCKED` or `FAILED` may be queued; anything else is `409`, audited as
       `dispatch_blocked` (`ALREADY_DISPATCHED` / `STATE_INVALID`).
    5. The gate, locked. Refused -> `BLOCKED` (re-submittable without re-signing, FEAT-11 R10), one
       `prescription.dispatch_blocked` event, `422` with the reason.
    6. Allowed -> `QUEUED`, one `dispatch_attempts` row (the outbox), one `prescription.dispatch`
       event carrying the approval and the key - all in this transaction. Nothing is sent here.
    """
    key = idempotency_key(
        tenant_id=tenant_id, prescription_id=prescription_id, client_key=client_key
    )
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor_id, actor_role=actor_role
    ) as session:
        row = _lock(session, tenant_id=tenant_id, prescription_id=prescription_id)
        if row is None:
            _record(
                session,
                action=DISPATCH,
                result="DENIED",
                resource_id=None,
                reason=CROSS_TENANT,
            )
            return Refusal(
                NOT_FOUND, status.HTTP_404_NOT_FOUND, "Prescription not found"
            )

        earlier = _replay(session, tenant_id=tenant_id, key=key)
        if earlier is not None:
            return DispatchResult(prescription=_read_one(session, row), replayed=True)

        if not identity.consume_step_up(
            session,
            tenant_id=tenant_id,
            user_id=actor_id,
            operation=DISPATCH,
            resource_id=row.id,
            token=step_up_token,
        ):
            return Refusal(
                identity.STEP_UP_REQUIRED,
                status.HTTP_403_FORBIDDEN,
                "Sending a prescription needs a fresh step-up: re-enter your password",
            )

        if row.state not in DISPATCHABLE_STATES:
            reason = (
                ALREADY_DISPATCHED if row.state in _IN_FLIGHT_STATES else STATE_INVALID
            )
            _record(
                session,
                action=DISPATCH_BLOCKED,
                result="DENIED",
                resource_id=row.id,
                reason=reason,
                payload={"block_reason": reason},
            )
            return Refusal(
                INVALID_STATE_TRANSITION,
                status.HTTP_409_CONFLICT,
                f"A {row.state} prescription cannot be dispatched",
            )

        decision = gate.decide(session, row)
        if not decision.allowed:
            if row.state != "BLOCKED":
                _transition(
                    session,
                    row,
                    to_state="BLOCKED",
                    actor_id=actor_id,
                    reason=decision.reason_code,
                )
            _record(
                session,
                action=DISPATCH_BLOCKED,
                result="DENIED",
                resource_id=row.id,
                reason=decision.reason_code,
                payload={"block_reason": decision.reason_code},
            )
            return Refusal(
                decision.reason_code or "TGA_APPROVAL_NOT_FOUND",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                gate.REFUSAL_MESSAGE,
            )

        previous_seq = session.exec(
            select(func.coalesce(func.max(DispatchAttempt.attempt_seq), 0)).where(
                DispatchAttempt.tenant_id == tenant_id,
                DispatchAttempt.prescription_id == row.id,
            )
        ).one()
        assert decision.approval_id is not None
        row.approval_id = decision.approval_id
        _transition(session, row, to_state="QUEUED", actor_id=actor_id)
        session.add(
            DispatchAttempt(
                tenant_id=tenant_id,
                prescription_id=row.id,
                approval_id=decision.approval_id,
                idempotency_key=key,
                attempt_seq=int(previous_seq) + 1,
                state="QUEUED",
                request_payload_hash=row.payload_hash or _payload_hash(row),
                requested_by=actor_id,
            )
        )
        session.flush()
        _record(
            session,
            action=DISPATCH,
            result="SUCCESS",
            resource_id=row.id,
            payload={
                "approval_id": str(decision.approval_id),
                "idempotency_key": key,
            },
        )
        return DispatchResult(prescription=_read_one(session, row), replayed=False)
