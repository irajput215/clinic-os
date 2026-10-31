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
from app.core.reads import Pending, Plan, ReadBatch
from app.modules.audit import service as audit
from app.modules.care_relationships import service as care
from app.modules.identity_tenancy import service as identity
from app.modules.patients import service as patients_service
from app.modules.prescriptions import gate
from app.modules.prescriptions.models import (
    LEGAL_TRANSITIONS,
    PRESCRIPTION_STATES,
    SUPERSEDED_BY_ADDENDUM,
    DispatchAttempt,
    Prescription,
    PrescriptionEvent,
)
from app.modules.prescriptions.schemas import (
    DispatchRead,
    PrescriberRead,
    PrescribersPublic,
    PrescriptionAddendum,
    PrescriptionCreate,
    PrescriptionEventRead,
    PrescriptionHistory,
    PrescriptionQueueSummary,
    PrescriptionRead,
    PrescriptionsPublic,
    PrescriptionUpdate,
)
from app.modules.prescriptions.transport import configured_transport
from app.modules.tga_approvals.schemas import TgaMatchResponse
from app.modules.users_roles import onboarding
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import PRESCRIPTION_PERMISSIONS
from app.modules.users_roles.policy import Actor, Decision

# The closed catalogue's actions (`app/modules/audit/actions.py`).
CREATE: Final[str] = "prescription.create"
# A draft edit, and the new version an addendum creates (FEAT-11 R3, R5; `05-data-and-audit.md`).
MODIFY: Final[str] = "prescription.modify"
# A cancellation (`05-data-and-audit.md`: `PRESCRIPTION_CANCELLED` is doc 07's `prescription.reject`).
REJECT: Final[str] = "prescription.reject"
# Registered with T1-34: a read of scripts, once per page (per patient on a patient's page), never
# once per row (`11-prescribing/02-user-stories.md`).
READ: Final[str] = "prescription.read"
# A script is part of its patient's record: reaching a patient's scripts, or staging one, is decided as
# a `patient:read` of that patient under the treating-relationship rule (T1-34, D-007).
PATIENT_ACCESS_PERMISSION: Final[str] = "patient:read"
SIGN: Final[str] = "prescription.sign"
DISPATCH: Final[str] = "prescription.dispatch"
DISPATCH_BLOCKED: Final[str] = "prescription.dispatch_blocked"

# Refusal codes.
NOT_FOUND: Final[str] = "PRESCRIPTION_NOT_FOUND"
CROSS_TENANT: Final[str] = "CROSS_TENANT"
PATIENT_NOT_FOUND: Final[str] = "PATIENT_NOT_FOUND"
PATIENT_BLOCKED: Final[str] = "PATIENT_BLOCKED"
PRESCRIBER_NOT_AUTHORIZED: Final[str] = "PRESCRIBER_NOT_AUTHORIZED"
NOT_PRESCRIBER_OF_RECORD: Final[str] = "NOT_PRESCRIBER_OF_RECORD"
INVALID_STATE_TRANSITION: Final[str] = "INVALID_STATE_TRANSITION"
IDEMPOTENCY_KEY_REQUIRED: Final[str] = "IDEMPOTENCY_KEY_REQUIRED"
# FEAT-10's block reasons for the non-gate refusals at dispatch (step 9).
ALREADY_DISPATCHED: Final[str] = "ALREADY_DISPATCHED"
# Editing or cancelling is for the script's own people: who drafted it, or its prescriber of record
# (FEAT-11 US-2; decision D-010).
NOT_DRAFTER_OR_PRESCRIBER: Final[str] = "NOT_DRAFTER_OR_PRESCRIBER"
# An original already corrected by an addendum (one addendum per original; correct the addendum).
ALREADY_SUPERSEDED: Final[str] = "ALREADY_SUPERSEDED"
# The event `reason` a new addendum version starts with.
ADDENDUM: Final[str] = "ADDENDUM"
# Where each write may start from (FEAT-11 state machine; decision D-010). Editing is a draft's;
# cancelling is anything not yet handed to the outbox (`QUEUED`, in flight, is never cancelled here,
# and a dispatched script is reversed, not cancelled); an addendum corrects a signed script that has
# not been sent.
EDITABLE_STATES: Final[frozenset[str]] = frozenset({"DRAFT"})
CANCELLABLE_STATES: Final[frozenset[str]] = frozenset(
    {"DRAFT", "SIGNED", "BLOCKED", "FAILED"}
)
AMENDABLE_STATES: Final[frozenset[str]] = frozenset({"SIGNED", "BLOCKED", "FAILED"})
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
# How many actionable prescriptions the Today page's "blocked" count asks the gate about.
GATE_SCAN_LIMIT: Final[int] = 100
_CURSOR_CONTEXT: Final[bytes] = b"clinos.prescriptions.cursor.v1"


@dataclass(frozen=True)
class Refusal:
    """A refused operation: the code, the status and the sentence the client is shown."""

    code: str
    status_code: int
    message: str
    #: `PRESCRIBER_NOT_READY` only: what the signer's onboarding pack lacks (docs3 feature 02, R15).
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchResult:
    """The prescription after a dispatch, and whether this answer replays an earlier request."""

    prescription: PrescriptionRead
    replayed: bool


@dataclass(frozen=True)
class PrescriptionsPage:
    """A page, or the treating-relationship refusal (`decision`) for a patient's page."""

    page: PrescriptionsPublic | None
    decision: Decision | None = None


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


def _queue_latest_attempts(
    batch: ReadBatch, *, tenant_id: uuid.UUID, prescription_ids: Sequence[uuid.UUID]
) -> Pending[dict[uuid.UUID, DispatchAttempt]]:
    """Each prescription's latest dispatch attempt, queued on the caller's batch."""
    if not prescription_ids:
        return Pending.ready({})
    attempts = batch.scalars(
        select(DispatchAttempt)
        .where(
            DispatchAttempt.tenant_id == tenant_id,
            col(DispatchAttempt.prescription_id).in_(prescription_ids),
        )
        .order_by(col(DispatchAttempt.attempt_seq))
    )
    # Ascending `attempt_seq`, so the last row of each prescription is its latest attempt.
    return attempts.then(lambda rows: {row.prescription_id: row for row in rows})


def _queue_reads(
    batch: ReadBatch, *, tenant_id: uuid.UUID, rows: Sequence[Prescription]
) -> Pending[list[PrescriptionRead]]:
    """Queue what converting `rows` needs: names, the latest dispatch and the live gate.

    Every lookup is one statement for the whole list, all of them in the caller's batch, so a page
    of prescriptions costs one round trip beyond its own read, however long it is.
    """
    patient_names = patients_service.queue_display_names(
        batch, tenant_id=tenant_id, patient_ids=[row.patient_id for row in rows]
    )
    people = users_roles.queue_display_names(
        batch,
        tenant_id=tenant_id,
        user_ids=[row.prescriber_id for row in rows] + [row.drafted_by for row in rows],
    )
    attempts = _queue_latest_attempts(
        batch, tenant_id=tenant_id, prescription_ids=[row.id for row in rows]
    )
    gates = gate.advise_many(
        batch, [row for row in rows if row.state in ACTIONABLE_STATES]
    )
    transport_configured = configured_transport() is not None

    def convert() -> list[PrescriptionRead]:
        return [
            _read_row(
                row,
                patient_name=patient_names.value.get(row.patient_id),
                people=people.value,
                attempt=attempts.value.get(row.id),
                gate_answer=gates.value.get(row.id),
                transport_configured=transport_configured,
            )
            for row in rows
        ]

    return Pending(convert)


def _read_row(
    row: Prescription,
    *,
    patient_name: str | None,
    people: dict[uuid.UUID, str],
    attempt: DispatchAttempt | None,
    gate_answer: TgaMatchResponse | None,
    transport_configured: bool,
) -> PrescriptionRead:
    return PrescriptionRead(
        id=row.id,
        patient_id=row.patient_id,
        patient_name=patient_name,
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
        cancel_reason_code=row.cancel_reason_code,
        supersedes_id=row.supersedes_id,
        # Only an actionable prescription carries the gate (`ACTIONABLE_STATES`).
        gate=gate_answer,
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


def _reads(
    session: Session, *, tenant_id: uuid.UUID, rows: Sequence[Prescription]
) -> list[PrescriptionRead]:
    """Convert rows inside the transaction, with names, the latest dispatch and the live gate."""
    batch = ReadBatch()
    reads = _queue_reads(batch, tenant_id=tenant_id, rows=rows)
    batch.send(session)
    return reads.value


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
    actor: Actor,
    states: Sequence[str] = (),
    prescriber_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> PrescriptionsPage:
    """One keyset page, newest first. Actionable rows carry the gate as it answers **now** (R2).

    Audited once per page as `prescription.read` (T1-34). A patient's page (`patient_id`) runs the
    treating-relationship rule for that patient - the relationship travels with the page in one
    flight - and records the relationship id and the purpose; a relationship-bound reader without one
    is refused `403` and audited `DENIED`. The queue records the kinds of filter and the row count.
    """
    tenant_id = actor.tenant_id
    decoded = None if cursor is None else decode_cursor(cursor)
    with tenant_transaction(
        tenant_id=tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
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
        first = ReadBatch()
        found = first.scalars(
            select(Prescription)
            .where(*conditions)
            .order_by(col(Prescription.created_at).desc(), col(Prescription.id).desc())
            .limit(limit + 1)
        )
        patient = (
            None
            if patient_id is None
            else patients_service.queue_display_names(
                first, tenant_id=tenant_id, patient_ids=[patient_id]
            )
        )
        relationship = (
            None
            if patient_id is None
            else first.scalars(select(care.actor_relationship_id(actor, patient_id)))
        )
        first.send(session)

        payload: dict[str, Any]
        if patient_id is None or patient is None or relationship is None:
            payload = {
                "query_filters": sorted(
                    kind
                    for kind, used in (
                        ("state", bool(states)),
                        ("prescriber", prescriber_id is not None),
                    )
                    if used
                )
            }
        elif patient_id not in patient.value:
            # Not one of the caller's patients: nothing of theirs can match, and the page is empty.
            payload = {"patient_id": str(patient_id)}
        else:
            access = care.patient_access(
                actor,
                PATIENT_ACCESS_PERMISSION,
                patient_id=patient_id,
                care_relationship_id=relationship.value[0],
            )
            if not access.allowed:
                _record(
                    session,
                    action=READ,
                    result="DENIED",
                    resource_id=None,
                    reason=access.reason,
                    payload={"patient_id": str(patient_id)},
                )
                return PrescriptionsPage(page=None, decision=access.decision)
            payload = {"patient_id": str(patient_id), **access.audit_payload()}

        rows = found.value
        page, overflow = list(rows[:limit]), rows[limit:]
        result = PrescriptionsPublic(
            data=_reads(session, tenant_id=tenant_id, rows=page),
            next_cursor=encode_cursor(page[-1]) if overflow else None,
        )
        _record(
            session,
            action=READ,
            result="SUCCESS",
            resource_id=None,
            payload={**payload, "result_count": len(result.data)},
        )
        return PrescriptionsPage(page=result)


def read_event(*, query_filters: list[str], result_count: int) -> audit.AuditEvent:
    """The `prescription.read` event for a practice-wide read: filter kinds and a count only."""
    return audit.AuditEvent(
        action=READ,
        result="SUCCESS",
        payload={"query_filters": query_filters, "result_count": result_count},
    )


def queue_summary_plan(
    *, tenant_id: uuid.UUID, limit: int
) -> Plan[PrescriptionQueueSummary]:
    """The queue at a glance, on the caller's transaction: every state's count, the newest `limit`
    prescriptions still needing a human action with the gate's answer **now**, and how many of the
    newest `GATE_SCAN_LIMIT` actionable ones that answer refuses.

    For the Today page (`dashboard` module), as a read plan (`app.core.reads`): the counts and the
    actionable rows are one step; the shown rows' names and dispatch, and the gate's answer for every
    scanned row, are the next. The gate here is `gate.advise_many`, which authorises nothing: signing
    and dispatch re-ask `gate.decide` on their own transaction. The scan is bounded, and
    `gate_checked` says how many prescriptions it asked about.
    """
    first = ReadBatch()
    counts = first.rows(
        select(col(Prescription.state), func.count())
        .where(col(Prescription.tenant_id) == tenant_id)
        .group_by(col(Prescription.state))
    )
    actionable = first.scalars(
        select(Prescription)
        .where(
            col(Prescription.tenant_id) == tenant_id,
            col(Prescription.state).in_(sorted(ACTIONABLE_STATES)),
        )
        .order_by(col(Prescription.created_at).desc(), col(Prescription.id).desc())
        .limit(max(limit, GATE_SCAN_LIMIT))
    )
    yield first

    rows = actionable.value
    second = ReadBatch()
    shown = _queue_reads(second, tenant_id=tenant_id, rows=rows[:limit])
    scanned = gate.advise_many(second, rows[limit:])
    yield second

    by_state = dict.fromkeys(PRESCRIPTION_STATES, 0)
    for state, total in counts.value:
        by_state[state] = total
    refused = sum(
        1 for read in shown.value if read.gate is not None and not read.gate.matched
    )
    refused += sum(1 for answer in scanned.value.values() if not answer.matched)
    return PrescriptionQueueSummary(
        by_state=by_state,
        transport_configured=configured_transport() is not None,
        actionable=shown.value,
        gate_refused=refused,
        gate_checked=len(rows),
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
    actor: Actor,
    body: PrescriptionCreate,
) -> PrescriptionRead | Refusal:
    """Create a `DRAFT` for a patient of this tenant, addressed to a prescriber who may sign it.

    The patient and the actor's relationship with it are resolved in one statement through the
    patients facade; staging for a patient a relationship-bound grant cannot reach is refused
    `403 AUTHZ_CARE_RELATIONSHIP_DENIED` and audited (`11-prescribing` US-1: "active care
    relationship"; T1-34).
    """
    tenant_id, actor_id, actor_role = actor.tenant_id, actor.user_id, actor.actor_role
    resolved = patients_service.patient_access(
        actor=actor, patient_id=body.patient_id, permission=PATIENT_ACCESS_PERMISSION
    )
    patient = resolved.patient
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
        if resolved.access is not None and not resolved.access.allowed:
            decision = resolved.access.decision
            _record(
                session,
                action=CREATE,
                result="DENIED",
                resource_id=None,
                reason=decision.code.value,
                payload={"patient_id": str(body.patient_id)},
            )
            return Refusal(decision.code.value, decision.status_code, decision.message)
        if patient.status == "BLOCKED":
            # Manual §3.2: a blocked patient takes no new script until the block is resolved.
            _record(
                session,
                action=CREATE,
                result="DENIED",
                resource_id=None,
                reason=PATIENT_BLOCKED,
                payload={"patient_id": str(body.patient_id)},
            )
            return Refusal(
                PATIENT_BLOCKED,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "This patient is blocked. Lift the block on their record before staging a script.",
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

        # docs3 feature 02 (R15, D8): the signer's onboarding pack, on this transaction, before the
        # safety gate. Fails closed: a person with no pack at all is missing everything.
        not_ready = onboarding.signing_readiness(
            session, tenant_id=tenant_id, user_id=actor_id
        )
        if not_ready is not None:
            _record(
                session,
                action=SIGN,
                result="DENIED",
                resource_id=row.id,
                reason=onboarding.PRESCRIBER_NOT_READY,
                payload={"patient_id": str(row.patient_id)},
            )
            return Refusal(
                onboarding.PRESCRIBER_NOT_READY,
                status.HTTP_403_FORBIDDEN,
                "Your onboarding pack isn't complete yet, so you can't sign scripts.",
                missing=tuple(not_ready.missing),
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


# --------------------------------------------------------------------------------------------
# One prescription: read, history, edit, cancel, addendum (FEAT-11; docs2 07; decision D-010)
# --------------------------------------------------------------------------------------------
#
# Every route below loads the row **with the actor's care relationship to its patient** in one
# statement (`care_relationships.service.relationship_id`, correlated on the row's own `patient_id`),
# under the request's tenant context and RLS. The order is the design's: absent or another tenant's
# is `404`; one of this tenant's whose patient a relationship-bound grant cannot reach is
# `403 AUTHZ_CARE_RELATIONSHIP_DENIED`; then the resource rules (who may act) and the state machine
# (`409 INVALID_STATE_TRANSITION`). Every refusal is audited with its reason on the same transaction.


def _load(
    session: Session, *, actor: Actor, prescription_id: uuid.UUID, lock: bool = False
) -> tuple[Prescription, care.PatientAccess] | None:
    statement = select(
        Prescription, care.actor_relationship_id(actor, col(Prescription.patient_id))
    ).where(
        Prescription.id == prescription_id, Prescription.tenant_id == actor.tenant_id
    )
    if lock:
        statement = statement.with_for_update(of=Prescription).execution_options(
            populate_existing=True
        )
    found = session.exec(statement).first()
    if found is None:
        return None
    row, relationship = found
    return row, care.patient_access(
        actor,
        PATIENT_ACCESS_PERMISSION,
        patient_id=row.patient_id,
        care_relationship_id=relationship,
    )


def _transaction(actor: Actor) -> Any:  # noqa: ANN401 - a context manager
    return tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    )


def _not_found(session: Session, *, action: str, prescription_id: uuid.UUID) -> Refusal:
    _record(
        session,
        action=action,
        result="DENIED",
        resource_id=prescription_id,
        reason=CROSS_TENANT,
    )
    return Refusal(NOT_FOUND, status.HTTP_404_NOT_FOUND, "Prescription not found")


def _refuse(
    session: Session,
    *,
    action: str,
    row: Prescription,
    code: str,
    status_code: int,
    message: str,
) -> Refusal:
    _record(
        session,
        action=action,
        result="DENIED",
        resource_id=row.id,
        reason=code,
        payload={"patient_id": str(row.patient_id)},
    )
    return Refusal(code, status_code, message)


def _access_refusal(
    session: Session, *, action: str, row: Prescription, access: care.PatientAccess
) -> Refusal | None:
    if access.allowed:
        return None
    decision = access.decision
    return _refuse(
        session,
        action=action,
        row=row,
        code=decision.code.value,
        status_code=decision.status_code,
        message=decision.message,
    )


def _wrong_state(session: Session, *, action: str, row: Prescription) -> Refusal:
    return _refuse(
        session,
        action=action,
        row=row,
        code=INVALID_STATE_TRANSITION,
        status_code=status.HTTP_409_CONFLICT,
        message=f"A {row.state.lower()} prescription cannot be changed this way",
    )


def _own(
    session: Session, *, action: str, row: Prescription, actor: Actor
) -> Refusal | None:
    """Only who drafted the script, or its prescriber of record, may edit or cancel it (US-2)."""
    if actor.user_id in (row.drafted_by, row.prescriber_id):
        return None
    return _refuse(
        session,
        action=action,
        row=row,
        code=NOT_DRAFTER_OR_PRESCRIBER,
        status_code=status.HTTP_403_FORBIDDEN,
        message="Only the clinician who drafted this script, or its prescriber, can change it",
    )


def read_one(*, actor: Actor, prescription_id: uuid.UUID) -> PrescriptionRead | Refusal:
    """One prescription, audited `prescription.read` with the relationship and purpose (US-7)."""
    with _transaction(actor) as session:
        found = _load(session, actor=actor, prescription_id=prescription_id)
        if found is None:
            return _not_found(session, action=READ, prescription_id=prescription_id)
        row, access = found
        if (
            refused := _access_refusal(session, action=READ, row=row, access=access)
        ) is not None:
            return refused
        read = _reads(session, tenant_id=actor.tenant_id, rows=[row])[0]
        _record(
            session,
            action=READ,
            result="SUCCESS",
            resource_id=row.id,
            payload={
                "patient_id": str(row.patient_id),
                "result_count": 1,
                **access.audit_payload(),
            },
        )
        return read


def history(
    *, actor: Actor, prescription_id: uuid.UUID
) -> PrescriptionHistory | Refusal:
    """The ordered transitions of one prescription (US-10), with who made each; audited as a read."""
    with _transaction(actor) as session:
        found = _load(session, actor=actor, prescription_id=prescription_id)
        if found is None:
            return _not_found(session, action=READ, prescription_id=prescription_id)
        row, access = found
        if (
            refused := _access_refusal(session, action=READ, row=row, access=access)
        ) is not None:
            return refused
        batch = ReadBatch()
        events = batch.scalars(
            select(PrescriptionEvent)
            .where(
                col(PrescriptionEvent.tenant_id) == actor.tenant_id,
                col(PrescriptionEvent.prescription_id) == row.id,
            )
            .order_by(col(PrescriptionEvent.occurred_at), col(PrescriptionEvent.id))
        )
        successor = batch.scalars(
            select(col(Prescription.id)).where(
                col(Prescription.tenant_id) == actor.tenant_id,
                col(Prescription.supersedes_id) == row.id,
            )
        )
        batch.send(session)
        names_batch = ReadBatch()
        names = users_roles.queue_display_names(
            names_batch,
            tenant_id=actor.tenant_id,
            user_ids=[e.actor_id for e in events.value if e.actor_id is not None],
        )
        names_batch.send(session)
        data = [
            PrescriptionEventRead(
                from_state=event.from_state,
                to_state=event.to_state,
                reason=event.reason,
                actor_id=event.actor_id,
                actor_name=None
                if event.actor_id is None
                else names.value.get(event.actor_id),
                occurred_at=event.occurred_at,
            )
            for event in events.value
        ]
        _record(
            session,
            action=READ,
            result="SUCCESS",
            resource_id=row.id,
            payload={
                "patient_id": str(row.patient_id),
                "query_filters": ["history"],
                "result_count": len(data),
                **access.audit_payload(),
            },
        )
        return PrescriptionHistory(
            prescription_id=row.id,
            supersedes_id=row.supersedes_id,
            superseded_by_id=next(iter(successor.value), None),
            data=data,
        )


def modify(
    *, actor: Actor, prescription_id: uuid.UUID, body: PrescriptionUpdate
) -> PrescriptionRead | Refusal:
    """Correct a `DRAFT` (FEAT-11 R3, US-2). The event names the changed fields, never a value."""
    changes = body.changes()
    prescribers = (
        users_roles.holders_of(
            tenant_id=actor.tenant_id, permission=PRESCRIPTION_PERMISSIONS["sign"]
        )
        if "prescriber_id" in changes
        else {}
    )
    with _transaction(actor) as session:
        found = _load(session, actor=actor, prescription_id=prescription_id, lock=True)
        if found is None:
            return _not_found(session, action=MODIFY, prescription_id=prescription_id)
        row, access = found
        if (
            refused := _access_refusal(session, action=MODIFY, row=row, access=access)
        ) is not None:
            return refused
        if (refused := _own(session, action=MODIFY, row=row, actor=actor)) is not None:
            return refused
        if row.state not in EDITABLE_STATES:
            return _wrong_state(session, action=MODIFY, row=row)
        if "prescriber_id" in changes and changes["prescriber_id"] not in prescribers:
            return _refuse(
                session,
                action=MODIFY,
                row=row,
                code=PRESCRIBER_NOT_AUTHORIZED,
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                message="Choose a prescriber in this organisation who may sign prescriptions",
            )
        for name, value in changes.items():
            setattr(row, name, value)
        session.add(row)
        session.flush()
        _record(
            session,
            action=MODIFY,
            result="SUCCESS",
            resource_id=row.id,
            payload={
                "patient_id": str(row.patient_id),
                "changed_fields": sorted(changes),
            },
        )
        return _read_one(session, row)


def cancel(
    *, actor: Actor, prescription_id: uuid.UUID, reason_code: str
) -> PrescriptionRead | Refusal:
    """Cancel before dispatch with a reason **code** (FEAT-11 R11, US-8; decision D-010).

    `DRAFT`, `SIGNED`, `BLOCKED` or `FAILED` -> `CANCELLED`; anything queued, sent or already terminal
    is `409`. The code goes on the row, on the history row and in the audit envelope's `reason`.
    """
    with _transaction(actor) as session:
        found = _load(session, actor=actor, prescription_id=prescription_id, lock=True)
        if found is None:
            return _not_found(session, action=REJECT, prescription_id=prescription_id)
        row, access = found
        if (
            refused := _access_refusal(session, action=REJECT, row=row, access=access)
        ) is not None:
            return refused
        if (refused := _own(session, action=REJECT, row=row, actor=actor)) is not None:
            return refused
        if row.state not in CANCELLABLE_STATES:
            return _wrong_state(session, action=REJECT, row=row)
        _cancel(session, row, actor_id=actor.user_id, reason_code=reason_code)
        return _read_one(session, row)


def _cancel(
    session: Session, row: Prescription, *, actor_id: uuid.UUID, reason_code: str
) -> None:
    previous = row.state
    # The code is set with the state, in one UPDATE: the row is `CANCELLED` exactly when it has one.
    row.cancel_reason_code = reason_code
    _transition(
        session, row, to_state="CANCELLED", actor_id=actor_id, reason=reason_code
    )
    _record(
        session,
        action=REJECT,
        result="SUCCESS",
        resource_id=row.id,
        reason=reason_code,
        payload={"patient_id": str(row.patient_id), "from_state": previous},
    )


@dataclass(frozen=True)
class AddendumResult:
    """The new version, and whether this answer replays an earlier request with the same key."""

    prescription: PrescriptionRead
    replayed: bool


_ADDENDUM_COPIED: Final[tuple[str, ...]] = (
    "patient_id",
    "prescriber_id",
    "medicine_name",
    "tga_category",
    "dosage_form",
    "dose_instruction",
    "quantity",
    "repeats",
    "triage_outcome",
    "conventional_therapy",
    "date_of_service",
)


def addendum(
    *,
    actor: Actor,
    prescription_id: uuid.UUID,
    body: PrescriptionAddendum,
    client_key: str,
) -> AddendumResult | Refusal:
    """Correct a signed script by a new version, never an edit (FEAT-11 R5, US-5; decision D-010).

    Only the original's prescriber of record may write it. In one transaction: the original (still
    `SIGNED`, `BLOCKED` or `FAILED`, so never sent) moves to `CANCELLED` with
    `SUPERSEDED_BY_ADDENDUM` - its payload and signature untouched - so exactly one live version
    exists; the new version is a `DRAFT` copying the original's payload with the corrections, naming
    the original in `supersedes_id`, to be signed through the gate like any script. The
    `Idempotency-Key` is hashed with the tenant and the original: the same key again answers the same
    addendum (`replayed`), another key `409 ALREADY_SUPERSEDED`.
    """
    key = idempotency_key(
        tenant_id=actor.tenant_id,
        prescription_id=prescription_id,
        client_key=client_key,
    )
    with _transaction(actor) as session:
        found = _load(session, actor=actor, prescription_id=prescription_id, lock=True)
        if found is None:
            return _not_found(session, action=MODIFY, prescription_id=prescription_id)
        original, access = found
        if (
            refused := _access_refusal(
                session, action=MODIFY, row=original, access=access
            )
        ) is not None:
            return refused
        if original.prescriber_id != actor.user_id:
            return _refuse(
                session,
                action=MODIFY,
                row=original,
                code=NOT_PRESCRIBER_OF_RECORD,
                status_code=status.HTTP_403_FORBIDDEN,
                message="Only the prescriber of record can amend a signed script",
            )
        existing = session.exec(
            select(Prescription).where(
                Prescription.tenant_id == actor.tenant_id,
                Prescription.supersedes_id == original.id,
            )
        ).first()
        if existing is not None:
            if existing.addendum_key == key:
                return AddendumResult(_read_one(session, existing), replayed=True)
            return _refuse(
                session,
                action=MODIFY,
                row=original,
                code=ALREADY_SUPERSEDED,
                status_code=status.HTTP_409_CONFLICT,
                message="This script already has an addendum; correct the addendum instead",
            )
        if original.state not in AMENDABLE_STATES:
            return _wrong_state(session, action=MODIFY, row=original)
        changes = body.changes()
        version = Prescription.model_validate(
            {
                **{
                    name: changes.get(name, getattr(original, name))
                    for name in _ADDENDUM_COPIED
                },
                "tenant_id": actor.tenant_id,
                "drafted_by": actor.user_id,
                "state": "DRAFT",
                "supersedes_id": original.id,
                "addendum_key": key,
            }
        )
        _cancel(
            session,
            original,
            actor_id=actor.user_id,
            reason_code=SUPERSEDED_BY_ADDENDUM,
        )
        session.add(version)
        session.flush()
        session.add(
            PrescriptionEvent(
                tenant_id=actor.tenant_id,
                prescription_id=version.id,
                from_state=None,
                to_state="DRAFT",
                reason=ADDENDUM,
                actor_id=actor.user_id,
            )
        )
        _record(
            session,
            action=MODIFY,
            result="SUCCESS",
            resource_id=version.id,
            reason=ADDENDUM,
            payload={
                "patient_id": str(version.patient_id),
                "changed_fields": sorted(changes),
                "supersedes_id": str(original.id),
            },
        )
        return AddendumResult(_read_one(session, version), replayed=False)
