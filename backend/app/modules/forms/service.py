"""Questionnaires: record a response, list a patient's history, acknowledge a safety flag.

docs3 Phase 6 feature 05 (`docs3/phase-6/05-forms-and-instruments/requirements.md`) R1-R9.

## Access

A response is clinical information, so it follows the clinical-record rules: recording needs
`clinical_record:write`, reading needs `clinical_record:read`, and both are subject to the
care-relationship rule (D-007) through `patients.patient_access`. A patient of another clinic is
`404`. Every decision, the refusals included, is audited, with the patient id and nothing clinical.

## Safety flags are raised in the response's own transaction

`score()` applies the flag rules, and every flag a response meets is inserted in the same transaction
as the response and its audit events. A response cannot exist without the flags it should have raised
(R3). Acknowledging needs `clinical_record:write` on the patient and an action code from the closed
list; a flag is never cleared without one (R4).
"""

import json
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

from fastapi import status
from sqlmodel import Session, col, select

from app.core import field_crypto
from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.forms.instruments import (
    ACKNOWLEDGE_ACTIONS,
    FLAG_RULES,
    INSTRUMENTS,
    InvalidAnswers,
    score,
)
from app.modules.forms.models import FormResponse, SafetyFlag
from app.modules.forms.schemas import (
    AcknowledgeActionRead,
    BandRead,
    FormResponseCreate,
    FormResponseRead,
    InstrumentCatalogue,
    InstrumentCode,
    InstrumentRead,
    OptionRead,
    PatientForms,
    SafetyFlagRead,
)
from app.modules.patients import service as patients_service
from app.modules.users_roles.policy import Actor, Decision

WRITE: Final[str] = "clinical_record:write"
READ_PERMISSION: Final[str] = "clinical_record:read"
CREATE: Final[str] = "form_response.create"
READ: Final[str] = "form_response.read"
RAISE: Final[str] = "safety_flag.raise"
ACKNOWLEDGE: Final[str] = "safety_flag.acknowledge"
_ANSWERS_KIND: Final[str] = "form_responses.answers"
_RULE_TEXT: Final[dict[str, str]] = {rule.code: rule.description for rule in FLAG_RULES}


@dataclass(frozen=True)
class Refusal:
    code: str
    status_code: int
    message: str
    decision: Decision | None = None


def _transaction(actor: Actor) -> AbstractContextManager[Session]:
    return tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    )


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
    with _transaction(actor) as session:
        _record(
            session, action=action, resource_id=None, result="DENIED", reason=reason
        )


# -- the catalogue ------------------------------------------------------------------------------


def catalogue() -> InstrumentCatalogue:
    return InstrumentCatalogue(
        instruments=[
            InstrumentRead(
                code=cast(InstrumentCode, i.code),
                version=i.version,
                title=i.title,
                stem=i.stem,
                items=list(i.items),
                options=[OptionRead(label=o.label, value=o.value) for o in i.options],
                bands=[
                    BandRead(code=b.code, label=b.label, low=b.low, high=b.high)
                    for b in i.bands
                ],
                difficulty_question=i.difficulty_question,
                difficulty_options=list(i.difficulty_options),
                min_score=i.min_score,
                max_score=i.max_score,
            )
            for i in INSTRUMENTS.values()
        ],
        acknowledge_actions=[
            AcknowledgeActionRead(code=code, label=label)
            for code, label in ACKNOWLEDGE_ACTIONS.items()
        ],
    )


# -- access ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Access:
    care_relationship_id: uuid.UUID | None
    purpose: str


def _access(
    actor: Actor, patient_id: uuid.UUID, permission: str, action: str
) -> _Access | Refusal:
    """The patient and the actor's access to it, or the refusal, audited."""
    resolved = patients_service.patient_access(
        actor=actor, patient_id=patient_id, permission=permission
    )
    if resolved.patient is None or resolved.access is None:
        audit_denial(actor=actor, action=action, reason="PATIENT_NOT_FOUND")
        return Refusal(
            "PATIENT_NOT_FOUND", status.HTTP_404_NOT_FOUND, "Patient not found"
        )
    if not resolved.access.allowed:
        decision = resolved.access.decision
        audit_denial(actor=actor, action=action, reason=decision.code.value)
        return Refusal(
            decision.code.value, decision.status_code, decision.message, decision
        )
    return _Access(resolved.access.care_relationship_id, resolved.access.purpose)


# -- reads ----------------------------------------------------------------------------------------


def _flag_read(flag: SafetyFlag) -> SafetyFlagRead:
    return SafetyFlagRead(
        id=flag.id,
        response_id=flag.response_id,
        rule_code=flag.rule_code,
        description=_RULE_TEXT.get(flag.rule_code, flag.rule_code),
        status="OPEN" if flag.status == "OPEN" else "ACKNOWLEDGED",
        raised_at=flag.raised_at,
        acknowledged_by=flag.acknowledged_by,
        acknowledged_at=flag.acknowledged_at,
        action_code=flag.action_code,
    )


def _response_read(
    row: FormResponse, flags: list[SafetyFlag], corrected_by: uuid.UUID | None
) -> FormResponseRead:
    decrypted = field_crypto.decrypt(
        row.answers, tenant_id=row.tenant_id, kind=_ANSWERS_KIND
    )
    # A value that fails to decrypt reads as unavailable (field_crypto never raises with a value).
    body: dict[str, object] = json.loads(decrypted) if decrypted else {}
    raw_answers = body.get("answers")
    answers = [int(a) for a in raw_answers] if isinstance(raw_answers, list) else []
    raw_difficulty = body.get("difficulty")
    difficulty = raw_difficulty if isinstance(raw_difficulty, int) else None
    instrument = INSTRUMENTS.get(row.instrument)
    band_label = (
        next((b.label for b in instrument.bands if b.code == row.band), row.band)
        if instrument
        else row.band
    )
    return FormResponseRead(
        id=row.id,
        patient_id=row.patient_id,
        instrument=cast(InstrumentCode, row.instrument),
        instrument_version=row.instrument_version,
        answers=answers,
        difficulty=difficulty,
        total_score=row.total_score,
        band=row.band,
        band_label=band_label,
        entered_by=row.entered_by,
        corrects_id=row.corrects_id,
        corrected_by_id=corrected_by,
        created_at=row.created_at,
        flags=[_flag_read(f) for f in flags],
    )


def patient_forms(*, actor: Actor, patient_id: uuid.UUID) -> PatientForms | Refusal:
    """The patient's responses, newest first, and their open flags (R9). Audited."""
    access = _access(actor, patient_id, READ_PERMISSION, READ)
    if isinstance(access, Refusal):
        return access
    with _transaction(actor) as session:
        rows = list(
            session.exec(
                select(FormResponse)
                .where(
                    FormResponse.tenant_id == actor.tenant_id,
                    FormResponse.patient_id == patient_id,
                )
                .order_by(col(FormResponse.created_at).desc(), col(FormResponse.id))
                .limit(200)
            ).all()
        )
        flags = list(
            session.exec(
                select(SafetyFlag)
                .where(
                    SafetyFlag.tenant_id == actor.tenant_id,
                    SafetyFlag.patient_id == patient_id,
                )
                .order_by(col(SafetyFlag.raised_at).desc(), col(SafetyFlag.id))
            ).all()
        )
        by_response: dict[uuid.UUID, list[SafetyFlag]] = {}
        for flag in flags:
            by_response.setdefault(flag.response_id, []).append(flag)
        corrected_by = {r.corrects_id: r.id for r in rows if r.corrects_id is not None}
        payload: dict[str, object] = {
            "patient_id": str(patient_id),
            "purpose": access.purpose,
            "result_count": len(rows),
        }
        if access.care_relationship_id is not None:
            payload["care_relationship_id"] = str(access.care_relationship_id)
        _record(session, action=READ, resource_id=None, payload=payload)
        return PatientForms(
            responses=[
                _response_read(r, by_response.get(r.id, []), corrected_by.get(r.id))
                for r in rows
            ],
            open_flags=[_flag_read(f) for f in flags if f.status == "OPEN"],
        )


# -- writes ---------------------------------------------------------------------------------------


def record_response(
    *, actor: Actor, patient_id: uuid.UUID, body: FormResponseCreate
) -> FormResponseRead | Refusal:
    """Score the answers, store the response and raise its flags, in one transaction (R1-R5)."""
    access = _access(actor, patient_id, WRITE, CREATE)
    if isinstance(access, Refusal):
        return access
    instrument = INSTRUMENTS[body.instrument]
    if body.instrument_version != instrument.version:
        return Refusal(
            "INSTRUMENT_VERSION_STALE",
            status.HTTP_409_CONFLICT,
            "This questionnaire has a newer version; reload it and answer again",
        )
    try:
        scored = score(instrument, tuple(body.answers), body.difficulty)
    except InvalidAnswers as error:
        return Refusal(
            "INVALID_ANSWERS", status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        )
    with _transaction(actor) as session:
        if body.corrects_id is not None:
            original = session.exec(
                select(FormResponse).where(
                    FormResponse.id == body.corrects_id,
                    FormResponse.tenant_id == actor.tenant_id,
                    FormResponse.patient_id == patient_id,
                    FormResponse.instrument == body.instrument,
                )
            ).first()
            if original is None:
                return Refusal(
                    "CORRECTED_RESPONSE_NOT_FOUND",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "A correction must name an earlier response of the same questionnaire",
                )
        row = FormResponse(
            tenant_id=actor.tenant_id,
            patient_id=patient_id,
            instrument=instrument.code,
            instrument_version=instrument.version,
            answers=field_crypto.encrypt(
                json.dumps(
                    {"answers": list(body.answers), "difficulty": body.difficulty}
                ),
                tenant_id=actor.tenant_id,
                kind=_ANSWERS_KIND,
            ),
            total_score=scored.total,
            band=scored.band.code,
            entered_by=actor.user_id,
            corrects_id=body.corrects_id,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            action=CREATE,
            resource_id=row.id,
            payload={"patient_id": str(patient_id)},
        )
        flags: list[SafetyFlag] = []
        for rule in scored.flags:
            flag = SafetyFlag(
                tenant_id=actor.tenant_id,
                patient_id=patient_id,
                response_id=row.id,
                rule_code=rule.code,
            )
            session.add(flag)
            session.flush()
            _record(
                session,
                action=RAISE,
                resource_id=flag.id,
                payload={"patient_id": str(patient_id)},
            )
            flags.append(flag)
        session.refresh(row)
        return _response_read(row, flags, None)


def acknowledge_flag(
    *, actor: Actor, flag_id: uuid.UUID, action_code: str
) -> SafetyFlagRead | Refusal | None:
    """Acknowledge an open flag with an action (R4). `None` for absent or another clinic's."""
    with _transaction(actor) as session:
        flag = session.exec(
            select(SafetyFlag).where(
                SafetyFlag.id == flag_id, SafetyFlag.tenant_id == actor.tenant_id
            )
        ).first()
        if flag is None:
            _record(
                session,
                action=ACKNOWLEDGE,
                resource_id=None,
                result="DENIED",
                reason="NOT_FOUND",
            )
            return None
        patient_id = flag.patient_id
    access = _access(actor, patient_id, WRITE, ACKNOWLEDGE)
    if isinstance(access, Refusal):
        return access
    if action_code not in ACKNOWLEDGE_ACTIONS:
        return Refusal(
            "UNKNOWN_ACTION",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose an action from the list",
        )
    with _transaction(actor) as session:
        flag = session.exec(
            select(SafetyFlag)
            .where(SafetyFlag.id == flag_id, SafetyFlag.tenant_id == actor.tenant_id)
            .with_for_update()
        ).one()
        if flag.status != "OPEN":
            return Refusal(
                "FLAG_ALREADY_ACKNOWLEDGED",
                status.HTTP_409_CONFLICT,
                "This flag has already been acknowledged",
            )
        flag.status = "ACKNOWLEDGED"
        flag.acknowledged_by = actor.user_id
        flag.acknowledged_at = datetime.now(UTC)
        flag.action_code = action_code
        session.add(flag)
        session.flush()
        _record(
            session,
            action=ACKNOWLEDGE,
            resource_id=flag.id,
            payload={"patient_id": str(patient_id)},
        )
        return _flag_read(flag)
