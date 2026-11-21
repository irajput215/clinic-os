"""The TGA inbox review queue: read, claim, accept (or correct), reject, defer.

Design: `docs/features/09-tga-inbox/03-design.md` ("Queue and reprocess state machine", "Endpoints");
requirements R12, R14-R18; D-011 §2.

## Accept creates a `PENDING` approval, never an `ACTIVE` one

A reviewer who accepts the extracted values creates a `tga_approvals` row through that module's facade
(`create_from_inbox`), `PENDING`, `source = INBOX_EXTRACTION`, with the reviewer as `created_by`. It
becomes `ACTIVE` only through `POST /tga-approvals/{id}/verify` by a **second** clinician
(`ck_tga_approvals_four_eyes`). So the inbox never activates anything (R14), and the path from an
email to a dispensable script still crosses two independent people.

## Every decision is audited as `tga_approval.verify`

R16: *"every decision writes `tga_approval.verify`"*. Accept, reject and defer each write one, with the
message id as `resource_id` and the decision as the reason code (`ACCEPTED`, `CORRECTED`, `DEFERRED`
or the rejection reason). Queue and detail reads are audited as `tga_approval.read`.

## Claims

A reviewer claims a message before deciding it. The claim is a lease (`CLAIM_MINUTES`); a second
reviewer's claim on a live lease is refused `409 CLAIMED_BY_ANOTHER` (R17). The claim is checked
again, under `FOR UPDATE`, in the transaction that records the decision, so two people cannot decide
one message.
"""

import hashlib
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final, cast

from fastapi import status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core import field_crypto
from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.patients import service as patients_service
from app.modules.tga_approvals import service as approvals
from app.modules.tga_approvals.schemas import TgaApprovalCreate
from app.modules.tga_inbox import adapters, extraction
from app.modules.tga_inbox.models import (
    OPEN_STATES,
    TgaExtractionResult,
    TgaInboxAttachment,
    TgaInboxMessage,
)
from app.modules.tga_inbox.pipeline import subject_kind, value_kind
from app.modules.tga_inbox.schemas import (
    AcceptRequest,
    AttachmentRead,
    DecisionResult,
    DraftNote,
    ExtractedFieldRead,
    FieldName,
    InboxMessageDetail,
    InboxMessageSummary,
    InboxQueue,
    MatchCandidateRead,
    PatientTgaLetter,
)
from app.modules.users_roles.policy import Actor, Decision

READ: Final[str] = "tga_approval.read"
DECIDE: Final[str] = "tga_approval.verify"
CLAIM_MINUTES: Final[int] = 15
MAX_QUEUE: Final[int] = 100
# What an inbox approval records as its creation reason (a code, like every reason).
CREATION_REASON: Final[str] = "INBOX_EXTRACTION"


@dataclass(frozen=True)
class Refusal:
    code: str
    status_code: int
    message: str


def _refuse(code: str, status_code: int, message: str) -> Refusal:
    return Refusal(code=code, status_code=status_code, message=message)


# T2-32: *"a reviewer cannot verify a patient they may not access under the care-relationship rule"*.
# Accepting files an approval against a patient, and a candidate shows a patient's name and date of
# birth, so both need the reviewer to be able to read that patient. A role whose `patient:read` is
# relationship-bound (D-007) needs an active care relationship; an unconditional grant does not.
REVIEWER_PATIENT_PERMISSION: Final[str] = "patient:read"


def _patient_decision(actor: Actor, patient_id: uuid.UUID) -> Decision | None:
    """The policy decision for the reviewer on this patient; `None` when there is no such patient of
    this tenant (absent and another tenant's are one answer)."""
    resolved = patients_service.patient_access(
        actor=actor, patient_id=patient_id, permission=REVIEWER_PATIENT_PERMISSION
    )
    if resolved.patient is None or resolved.access is None:
        return None
    return resolved.access.decision


def _record(
    session: Session,
    *,
    action: str,
    resource_id: uuid.UUID | None,
    result: str = "SUCCESS",
    reason: str | None = None,
    payload: dict[str, object] | None = None,
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


def audit_denial(*, actor: Actor, action: str, reason: str) -> None:
    """A refusal the policy layer made, in its own transaction; a failure propagates (fail closed)."""
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    ) as session:
        _record(
            session, action=action, resource_id=None, result="DENIED", reason=reason
        )


def _transaction(actor: Actor) -> AbstractContextManager[Session]:
    return tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _decrypt(value: bytes | None, *, tenant_id: uuid.UUID, kind: str) -> str | None:
    return field_crypto.decrypt(value, tenant_id=tenant_id, kind=kind)


def _load(
    session: Session, *, tenant_id: uuid.UUID, message_id: uuid.UUID, lock: bool = False
) -> TgaInboxMessage | None:
    """One message of this tenant, or `None` for absent and for another tenant's alike (404)."""
    statement = select(TgaInboxMessage).where(
        TgaInboxMessage.id == message_id, TgaInboxMessage.tenant_id == tenant_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def _attachments(
    session: Session, *, tenant_id: uuid.UUID, message_id: uuid.UUID
) -> list[TgaInboxAttachment]:
    return list(
        session.exec(
            select(TgaInboxAttachment)
            .where(
                TgaInboxAttachment.tenant_id == tenant_id,
                TgaInboxAttachment.message_id == message_id,
            )
            .order_by(col(TgaInboxAttachment.created_at), col(TgaInboxAttachment.id))
        ).all()
    )


def _results(
    session: Session, *, tenant_id: uuid.UUID, attachment_ids: list[uuid.UUID]
) -> list[TgaExtractionResult]:
    """The newest extractor version's results per attachment."""
    if not attachment_ids:
        return []
    rows = session.exec(
        select(TgaExtractionResult).where(
            TgaExtractionResult.tenant_id == tenant_id,
            col(TgaExtractionResult.attachment_id).in_(attachment_ids),
        )
    ).all()
    newest: dict[uuid.UUID, str] = {}
    for row in rows:
        if (
            row.attachment_id not in newest
            or row.extractor_version > newest[row.attachment_id]
        ):
            newest[row.attachment_id] = row.extractor_version
    return [row for row in rows if row.extractor_version == newest[row.attachment_id]]


def _confidences(results: list[TgaExtractionResult]) -> dict[str, Decimal | None]:
    """Per field, the best confidence any attachment produced."""
    best: dict[str, Decimal | None] = {}
    for row in results:
        current = best.get(row.field_name)
        if row.confidence is not None and (current is None or row.confidence > current):
            best[row.field_name] = row.confidence
        else:
            best.setdefault(row.field_name, current)
    return best


def _summary(
    message: TgaInboxMessage,
    *,
    attachments: list[TgaInboxAttachment],
    results: list[TgaExtractionResult],
) -> dict[str, object]:
    return {
        "id": message.id,
        "received_at": message.received_at,
        "from_address": message.from_address,
        "subject": _decrypt(
            message.subject, tenant_id=message.tenant_id, kind=subject_kind()
        ),
        "processing_state": message.processing_state,
        "state_reason": message.state_reason,
        "attachment_count": len(attachments),
        "clean_attachment_count": sum(
            1 for a in attachments if a.object_key is not None
        ),
        "composite_score": extraction.composite_score(_confidences(results))
        if results
        else None,
        "claimed_by": message.claimed_by,
        "lease_expires_at": message.lease_expires_at,
    }


# -- reads --------------------------------------------------------------------------------------


def list_queue(*, actor: Actor, state: str | None, limit: int) -> InboxQueue:
    """Oldest first (R17); the open states by default. Audited as one practice-wide read."""
    states = (state,) if state else OPEN_STATES
    with _transaction(actor) as session:
        messages = list(
            session.exec(
                select(TgaInboxMessage)
                .where(
                    TgaInboxMessage.tenant_id == actor.tenant_id,
                    col(TgaInboxMessage.processing_state).in_(states),
                )
                .order_by(col(TgaInboxMessage.received_at), col(TgaInboxMessage.id))
                .limit(min(limit, MAX_QUEUE))
            ).all()
        )
        count = session.exec(
            select(func.count())
            .select_from(TgaInboxMessage)
            .where(
                TgaInboxMessage.tenant_id == actor.tenant_id,
                col(TgaInboxMessage.processing_state).in_(states),
            )
        ).one()
        data: list[InboxMessageSummary] = []
        for message in messages:
            attachments = _attachments(
                session, tenant_id=actor.tenant_id, message_id=message.id
            )
            results = _results(
                session,
                tenant_id=actor.tenant_id,
                attachment_ids=[a.id for a in attachments],
            )
            data.append(
                InboxMessageSummary.model_validate(
                    _summary(message, attachments=attachments, results=results)
                )
            )
        _record(
            session,
            action=READ,
            resource_id=None,
            payload={
                "query_filters": ["TGA_INBOX", *states],
                "result_count": len(data),
            },
        )
        return InboxQueue(data=data, count=int(count))


def _detail(
    session: Session, *, message: TgaInboxMessage, actor: Actor
) -> InboxMessageDetail:
    tenant_id = message.tenant_id
    attachments = _attachments(session, tenant_id=tenant_id, message_id=message.id)
    results = _results(
        session, tenant_id=tenant_id, attachment_ids=[a.id for a in attachments]
    )
    fields: list[ExtractedFieldRead] = []
    best: dict[str, str] = {}
    best_confidence: dict[str, Decimal] = {}
    for row in sorted(results, key=lambda r: (str(r.attachment_id), r.field_name)):
        value = _decrypt(
            row.raw_value, tenant_id=tenant_id, kind=value_kind(row.field_name)
        )
        fields.append(
            ExtractedFieldRead(
                attachment_id=row.attachment_id,
                field_name=cast(FieldName, row.field_name),
                value=value,
                confidence=row.confidence,
                method=row.method,
                page_number=row.page_number,
                below_floor=row.confidence is None
                or row.confidence < extraction.FIELD_FLOOR,
                mandatory=row.field_name in extraction.MANDATORY_FIELDS,
            )
        )
        if value is not None and row.confidence is not None:
            if (
                row.field_name not in best
                or row.confidence > best_confidence[row.field_name]
            ):
                best[row.field_name] = value
                best_confidence[row.field_name] = row.confidence
    candidates: list[MatchCandidateRead] = []
    if message.processing_state in OPEN_STATES and best:
        dob = best.get("PATIENT_DOB")
        for candidate in patients_service.inbox_match_candidates(
            session,
            tenant_id=tenant_id,
            full_name=best.get("PATIENT_NAME"),
            date_of_birth=extraction.parse_date(dob) if dob else None,
            ihi=best.get("PATIENT_IHI"),
            medicare=best.get("PATIENT_MEDICARE"),
        ):
            # A patient the reviewer may not read is not shown, so a proposal never discloses a
            # name or date of birth the care-relationship rule withholds (T2-32).
            decision = _patient_decision(actor, candidate.patient_id)
            if decision is None or not decision.allowed:
                continue
            candidates.append(
                MatchCandidateRead(
                    patient_id=candidate.patient_id,
                    display_name=candidate.display_name,
                    date_of_birth=candidate.date_of_birth,
                    agreed=list(candidate.agreed),
                )
            )
    return InboxMessageDetail.model_validate(
        {
            **_summary(message, attachments=attachments, results=results),
            "spf_result": message.spf_result,
            "dkim_result": message.dkim_result,
            "dmarc_result": message.dmarc_result,
            "decided_by": message.decided_by,
            "decided_at": message.decided_at,
            "decision_reason": message.decision_reason,
            "patient_id": message.patient_id,
            "approval_id": message.approval_id,
            "extractor_version": results[0].extractor_version if results else None,
            "attachments": [
                AttachmentRead(
                    id=a.id,
                    filename=a.original_filename,
                    content_type=a.content_type,
                    size_bytes=a.size_bytes,
                    scan_state=a.scan_state,
                    text_state=a.text_state,
                    page_count=a.page_count,
                    refusal_reason=a.refusal_reason,
                    viewable=a.object_key is not None,
                )
                for a in attachments
            ],
            "fields": fields,
            "candidates": candidates,
        }
    )


def read_message(*, actor: Actor, message_id: uuid.UUID) -> InboxMessageDetail | None:
    """The review screen's evidence: fields, confidence, provenance and candidates (R15)."""
    with _transaction(actor) as session:
        message = _load(session, tenant_id=actor.tenant_id, message_id=message_id)
        if message is None:
            _record(
                session,
                action=READ,
                resource_id=None,
                result="DENIED",
                reason="NOT_FOUND",
            )
            return None
        detail = _detail(session, message=message, actor=actor)
        _record(
            session,
            action=READ,
            resource_id=message.id,
            payload={"query_filters": ["TGA_INBOX_MESSAGE"], "result_count": 1},
        )
        return detail


class IntegrityFailure(Exception):
    """A stored original no longer matches the hash recorded at ingest (FEAT-09 R6)."""


def attachment_content(
    *, actor: Actor, attachment_id: uuid.UUID, store: adapters.ObjectStore | None = None
) -> tuple[str, bytes] | None:
    """`(display filename, bytes)` of a clean, stored attachment whose hash still verifies.

    `None` for absent, another tenant's, refused or not stored alike. A hash mismatch raises
    `IntegrityFailure`: retrieval is blocked, never served (R6).
    """
    resolved = store or adapters.configured_store()
    with _transaction(actor) as session:
        row = session.exec(
            select(TgaInboxAttachment).where(
                TgaInboxAttachment.id == attachment_id,
                TgaInboxAttachment.tenant_id == actor.tenant_id,
            )
        ).first()
        if row is None or row.object_key is None or row.scan_state != "CLEAN":
            _record(
                session,
                action=READ,
                resource_id=None,
                result="DENIED",
                reason="NOT_FOUND",
            )
            return None
        data = resolved.get(row.object_key)
        if data is None:
            _record(
                session,
                action=READ,
                resource_id=row.id,
                result="FAILED",
                reason="OBJECT_MISSING",
            )
            return None
        if hashlib.sha256(data).digest() != row.sha256:
            _record(
                session,
                action=READ,
                resource_id=row.id,
                result="FAILED",
                reason="HASH_MISMATCH",
            )
            raise IntegrityFailure
        _record(
            session,
            action=READ,
            resource_id=row.id,
            payload={"query_filters": ["TGA_INBOX_ATTACHMENT"], "result_count": 1},
        )
        return row.original_filename, data


# -- claims ---------------------------------------------------------------------------------------


def _claim_refusal(
    message: TgaInboxMessage, *, actor: Actor, now: datetime
) -> Refusal | None:
    if message.processing_state not in OPEN_STATES:
        return _refuse(
            "ALREADY_DECIDED",
            status.HTTP_409_CONFLICT,
            "This message has already been decided",
        )
    if (
        message.claimed_by is not None
        and message.claimed_by != actor.user_id
        and message.lease_expires_at is not None
        and message.lease_expires_at > now
    ):
        return _refuse(
            "CLAIMED_BY_ANOTHER",
            status.HTTP_409_CONFLICT,
            "Another reviewer is working on this message",
        )
    return None


def claim(
    *, actor: Actor, message_id: uuid.UUID
) -> InboxMessageDetail | Refusal | None:
    """Take (or renew) the lease on one message. `None` for absent or another tenant's."""
    now = _now()
    with _transaction(actor) as session:
        message = _load(
            session, tenant_id=actor.tenant_id, message_id=message_id, lock=True
        )
        if message is None:
            return None
        refusal = _claim_refusal(message, actor=actor, now=now)
        if refusal is not None:
            return refusal
        message.claimed_by = actor.user_id
        message.claimed_at = now
        message.lease_expires_at = now + timedelta(minutes=CLAIM_MINUTES)
        session.add(message)
        session.flush()
        return _detail(session, message=message, actor=actor)


def _holding(
    session: Session, *, actor: Actor, message_id: uuid.UUID
) -> TgaInboxMessage | Refusal | None:
    """The message, locked, if `actor` holds a live claim on it; otherwise the refusal."""
    message = _load(
        session, tenant_id=actor.tenant_id, message_id=message_id, lock=True
    )
    if message is None:
        return None
    now = _now()
    refusal = _claim_refusal(message, actor=actor, now=now)
    if refusal is not None:
        return refusal
    if (
        message.claimed_by != actor.user_id
        or message.lease_expires_at is None
        or message.lease_expires_at <= now
    ):
        return _refuse(
            "CLAIM_REQUIRED",
            status.HTTP_409_CONFLICT,
            "Claim the message before deciding it",
        )
    return message


def _release(message: TgaInboxMessage) -> None:
    message.claimed_by = None
    message.claimed_at = None
    message.lease_expires_at = None


# -- decisions ------------------------------------------------------------------------------------


def defer(*, actor: Actor, message_id: uuid.UUID) -> DecisionResult | Refusal | None:
    """Return the message to the queue (R16)."""
    with _transaction(actor) as session:
        held = _holding(session, actor=actor, message_id=message_id)
        if not isinstance(held, TgaInboxMessage):
            return held
        _release(held)
        session.add(held)
        _record(session, action=DECIDE, resource_id=held.id, reason="DEFERRED")
        return DecisionResult(
            message_id=held.id, processing_state=held.processing_state
        )


def reject(
    *, actor: Actor, message_id: uuid.UUID, reason_code: str
) -> DecisionResult | Refusal | None:
    """Not an approval this clinic should record (R16): a reason code is required."""
    with _transaction(actor) as session:
        held = _holding(session, actor=actor, message_id=message_id)
        if not isinstance(held, TgaInboxMessage):
            return held
        _release(held)
        held.processing_state = "REJECTED"
        held.decided_by = actor.user_id
        held.decided_at = _now()
        held.decision_reason = reason_code
        session.add(held)
        _record(session, action=DECIDE, resource_id=held.id, reason=reason_code)
        return DecisionResult(message_id=held.id, processing_state="REJECTED")


def accept(
    *, actor: Actor, message_id: uuid.UUID, request: AcceptRequest
) -> DecisionResult | Refusal | None:
    """Accept or correct the extracted values and create a `PENDING` approval (stage 12)."""
    # The reviewer must be able to read the chosen patient (T2-32). Decided before the decision's
    # transaction opens, as the approvals router does; the refusal is audited on its own transaction,
    # and nothing is written. `404` for a patient of no-one's or another tenant's; the policy's own
    # `403` (for example `AUTHZ_CARE_RELATIONSHIP_DENIED`) for a patient the reviewer may not access.
    decision = _patient_decision(actor, request.patient_id)
    if decision is None or not decision.allowed:
        reason = "PATIENT_NOT_FOUND" if decision is None else decision.code.value
        with _transaction(actor) as session:
            _record(
                session,
                action=DECIDE,
                resource_id=message_id,
                result="DENIED",
                reason=reason,
            )
        if decision is None:
            return _refuse(
                "PATIENT_NOT_FOUND", status.HTTP_404_NOT_FOUND, "Patient not found"
            )
        return _refuse(decision.code.value, decision.status_code, decision.message)
    try:
        with _transaction(actor) as session:
            held = _holding(session, actor=actor, message_id=message_id)
            if not isinstance(held, TgaInboxMessage):
                return held
            if held.state_reason == "UNTRUSTED_SENDER":
                return _refuse(
                    "UNTRUSTED_SENDER",
                    status.HTTP_409_CONFLICT,
                    "A message from an unverified sender can only be rejected",
                )
            attachment = session.exec(
                select(TgaInboxAttachment).where(
                    TgaInboxAttachment.id == request.attachment_id,
                    TgaInboxAttachment.tenant_id == actor.tenant_id,
                    TgaInboxAttachment.message_id == held.id,
                )
            ).first()
            if attachment is None or attachment.object_key is None:
                return _refuse(
                    "ATTACHMENT_NOT_USABLE",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Choose a stored, clean attachment of this message as the source document",
                )
            if not patients_service.live_patient_exists(
                session, tenant_id=actor.tenant_id, patient_id=request.patient_id
            ):
                return _refuse(
                    "PATIENT_NOT_FOUND", status.HTTP_404_NOT_FOUND, "Patient not found"
                )
            results = {
                row.field_name: row
                for row in _results(
                    session, tenant_id=actor.tenant_id, attachment_ids=[attachment.id]
                )
            }
            extracted = {
                name: _decrypt(
                    row.raw_value, tenant_id=actor.tenant_id, kind=value_kind(name)
                )
                for name, row in results.items()
            }
            final = {
                name: value for name, value in extracted.items() if value is not None
            }
            final.update(
                {name: value.strip() for name, value in request.values.items()}
            )
            corrected = any(
                extracted.get(name) != value.strip()
                for name, value in request.values.items()
            )
            if corrected and request.correction_reason is None:
                return _refuse(
                    "CORRECTION_REASON_REQUIRED",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "A corrected value needs a correction reason",
                )
            missing = [
                name for name in extraction.MANDATORY_FIELDS if not final.get(name)
            ]
            if missing:
                return _refuse(
                    "MANDATORY_FIELD_MISSING",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Missing: " + ", ".join(missing),
                )
            try:
                approval_in = TgaApprovalCreate(
                    patient_id=request.patient_id,
                    tga_category=final["TGA_CATEGORY"],
                    dosage_form=final["DOSAGE_FORM"],
                    approval_reference=final["APPROVAL_REFERENCE"],
                    creation_reason=CREATION_REASON,
                    valid_from=_iso(final["VALID_FROM"]),
                    valid_to=_iso(final["VALID_TO"]),
                )
            except ValidationError, ValueError:
                return _refuse(
                    "INVALID_APPROVAL_VALUES",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "The values do not form a valid approval (category, dosage form, reference or window)",
                )
            created = approvals.create_from_inbox(
                session,
                tenant_id=actor.tenant_id,
                actor_id=actor.user_id,
                approval_in=approval_in,
                source_document_id=attachment.id,
            )
            if isinstance(created, approvals.Refusal):
                return _refuse(created.code, created.status_code, created.message)
            now = _now()
            for name, value in final.items():
                row = results.get(name)
                if row is None:
                    continue
                row.accepted_value = field_crypto.encrypt(
                    value, tenant_id=actor.tenant_id, kind=value_kind(name)
                )
                row.accepted_by = actor.user_id
                row.accepted_at = now
                session.add(row)
            _release(held)
            held.processing_state = "VERIFIED"
            held.decided_by = actor.user_id
            held.decided_at = now
            held.decision_reason = (
                request.correction_reason if corrected else "ACCEPTED"
            )
            held.patient_id = request.patient_id
            held.approval_id = created.id
            session.add(held)
            _record(
                session,
                action=DECIDE,
                resource_id=held.id,
                reason="CORRECTED" if corrected else "ACCEPTED",
            )
            return DecisionResult(
                message_id=held.id, processing_state="VERIFIED", approval_id=created.id
            )
    except IntegrityError as error:
        refusal = approvals.constraint_refusal(error)
        return _refuse(refusal.code, refusal.status_code, refusal.message)


def _iso(value: str) -> date:
    parsed = extraction.parse_date(value)
    if parsed is None:
        raise ValueError("not a date")
    return parsed


# -- the draft note (D-011 §3, step 5) ---------------------------------------------------------------

# What a note drafted from a letter may say: the approval and who it names. No IHI, no Medicare number
# (the record already holds them), and no clinical judgement: the briefing-note rule (D11) applies.
_NOTE_DATE_FIELDS: Final[tuple[str, ...]] = ("VALID_FROM", "VALID_TO")


def _words(token: str) -> str:
    """A controlled token as words: `ORAL_LIQUID` -> `Oral liquid`, `CATEGORY_3` -> `Category 3`."""
    return token.replace("_", " ").capitalize()


def _long_date(value: str | None) -> str | None:
    parsed = extraction.parse_date(value) if value else None
    return f"{parsed.day} {parsed:%B %Y}" if parsed else value


def draft_note(
    *, received_at: datetime, sender: str, values: dict[str, str]
) -> DraftNote:
    """A factual SOAP draft from accepted values. Deterministic, so the same letter drafts the same
    note; the clinician edits it before saving."""
    received = received_at.astimezone(UTC)
    lines = [
        f"TGA approval letter received {received.day} {received:%B %Y} from {sender}.",
    ]
    reference = values.get("APPROVAL_REFERENCE")
    if reference:
        lines.append(f"Approval {reference}.")
    grant = ", ".join(
        _words(value)
        for value in (values.get("TGA_CATEGORY"), values.get("DOSAGE_FORM"))
        if value
    )
    if grant:
        lines.append(f"Approved: {grant}.")
    if values.get("VALID_FROM") or values.get("VALID_TO"):
        lines.append(
            f"Valid from {_long_date(values.get('VALID_FROM')) or 'not stated'} to "
            f"{_long_date(values.get('VALID_TO')) or 'not stated'} (end date as printed)."
        )
    prescriber = values.get("PRESCRIBER_NAME")
    if prescriber:
        hpi = values.get("PRESCRIBER_HPI_I")
        lines.append(
            f"Prescriber named on the letter: {prescriber}"
            + (f" (HPI-I {hpi})." if hpi else ".")
        )
    return DraftNote(
        subjective="",
        objective=" ".join(lines),
        assessment="",
        plan=(
            "Approval recorded as pending from the TGA inbox. Verify it on the approvals register "
            "before prescribing."
        ),
    )


def _accepted_values(
    session: Session, *, tenant_id: uuid.UUID, message_id: uuid.UUID
) -> dict[str, str]:
    attachment_ids = [
        a.id for a in _attachments(session, tenant_id=tenant_id, message_id=message_id)
    ]
    values: dict[str, str] = {}
    for row in _results(session, tenant_id=tenant_id, attachment_ids=attachment_ids):
        if row.accepted_value is None:
            continue
        value = _decrypt(
            row.accepted_value, tenant_id=tenant_id, kind=value_kind(row.field_name)
        )
        if value is not None:
            values[row.field_name] = value
    return values


class LetterRefusal(Exception):
    """The patient is not reachable (`404`) or the treating-relationship rule refused (the decision)."""

    def __init__(self, decision: Decision | None) -> None:
        super().__init__("refused")
        self.decision = decision


def letters_for_patient(
    *, actor: Actor, patient_id: uuid.UUID
) -> list[PatientTgaLetter]:
    """The patient's accepted TGA letters, newest first, each with a draft note (D-011 §3).

    `clinical_record:read` under the treating-relationship rule (D-007), like the intake briefing:
    a letter is clinical context. A patient of another tenant is `404`; a refused relationship is the
    policy's own answer. Both are audited, and so is the read.
    """
    resolved = patients_service.patient_access(
        actor=actor, patient_id=patient_id, permission="clinical_record:read"
    )
    if (
        resolved.patient is None
        or resolved.access is None
        or not resolved.access.allowed
    ):
        with _transaction(actor) as session:
            _record(
                session,
                action=READ,
                resource_id=None,
                result="DENIED",
                reason="NOT_FOUND"
                if resolved.patient is None or resolved.access is None
                else resolved.access.decision.code.value,
            )
        raise LetterRefusal(
            None if resolved.access is None else resolved.access.decision
        )
    access = resolved.access
    with _transaction(actor) as session:
        messages = session.exec(
            select(TgaInboxMessage)
            .where(
                TgaInboxMessage.tenant_id == actor.tenant_id,
                TgaInboxMessage.patient_id == patient_id,
                TgaInboxMessage.processing_state == "VERIFIED",
            )
            .order_by(col(TgaInboxMessage.decided_at).desc(), col(TgaInboxMessage.id))
            .limit(20)
        ).all()
        letters: list[PatientTgaLetter] = []
        for message in messages:
            values = _accepted_values(
                session, tenant_id=actor.tenant_id, message_id=message.id
            )
            letters.append(
                PatientTgaLetter(
                    message_id=message.id,
                    received_at=message.received_at,
                    decided_at=message.decided_at,
                    approval_id=message.approval_id,
                    values=cast(dict[FieldName, str], values),
                    draft_note=draft_note(
                        received_at=message.received_at,
                        sender=message.from_address,
                        values=values,
                    ),
                )
            )
        payload: dict[str, object] = {
            "patient_id": str(patient_id),
            "purpose": access.purpose,
            "result_count": len(letters),
        }
        if access.care_relationship_id is not None:
            payload["care_relationship_id"] = str(access.care_relationship_id)
        _record(session, action=READ, resource_id=None, payload=payload)
        return letters
