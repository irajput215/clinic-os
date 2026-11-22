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
from datetime import UTC, date, datetime
from typing import Final, cast

from fastapi import status
from sqlmodel import Session, col, func, select

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
from app.modules.forms.models import (
    ClinicForm,
    ClinicFormResponse,
    ClinicFormVersion,
    FormResponse,
    SafetyFlag,
)
from app.modules.forms.schemas import (
    AcknowledgeActionRead,
    AnswerValue,
    BandRead,
    ClinicFormField,
    ClinicFormRead,
    ClinicFormResponseCreate,
    ClinicFormResponseRead,
    ClinicFormWrite,
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
            "result_count": len(rows)
            + session.exec(
                select(func.count())
                .select_from(ClinicFormResponse)
                .where(
                    ClinicFormResponse.tenant_id == actor.tenant_id,
                    ClinicFormResponse.patient_id == patient_id,
                )
            ).one(),
        }
        if access.care_relationship_id is not None:
            payload["care_relationship_id"] = str(access.care_relationship_id)
        _record(session, action=READ, resource_id=None, payload=payload)
        clinic_responses = _clinic_responses(session, actor.tenant_id, patient_id)
        return PatientForms(
            clinic_responses=clinic_responses,
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


# -- clinic-made forms (R6) -------------------------------------------------------------------------
#
# A practice owner (`tenant:configure`) builds a form from the small field vocabulary in
# `schemas.ClinicFormField` and publishes it; editing publishes the next version, and a published
# version never changes. Staff record responses under the same rules as the instruments
# (`clinical_record:write` / `read` with the care relationship). Clinic forms are not scored and raise
# no safety flags (D20 keeps flag rules with the Clinical Safety Officer).

CONFIGURE: Final[str] = "tenant:configure"
PUBLISH_FORM: Final[str] = "form.publish"
RETIRE_FORM: Final[str] = "form.retire"
_CLINIC_ANSWERS_KIND: Final[str] = "clinic_form_responses.answers"
_TEXT_LIMITS: Final[dict[str, int]] = {"TEXT": 500, "LONG_TEXT": 5000}


def _version_read(form: ClinicForm, version: ClinicFormVersion) -> ClinicFormRead:
    return ClinicFormRead(
        id=form.id,
        status="ACTIVE" if form.status == "ACTIVE" else "RETIRED",
        version_id=version.id,
        version=version.version,
        title=version.title,
        description=version.description,
        fields=[ClinicFormField.model_validate(f) for f in version.fields],
        published_at=version.published_at,
    )


def _latest_versions(
    session: Session, tenant_id: uuid.UUID
) -> dict[uuid.UUID, ClinicFormVersion]:
    rows = session.exec(
        select(ClinicFormVersion)
        .where(ClinicFormVersion.tenant_id == tenant_id)
        .order_by(col(ClinicFormVersion.form_id), col(ClinicFormVersion.version).desc())
    ).all()
    latest: dict[uuid.UUID, ClinicFormVersion] = {}
    for row in rows:
        latest.setdefault(row.form_id, row)
    return latest


def list_clinic_forms(*, actor: Actor, include_retired: bool) -> list[ClinicFormRead]:
    with _transaction(actor) as session:
        forms = session.exec(
            select(ClinicForm)
            .where(ClinicForm.tenant_id == actor.tenant_id)
            .order_by(col(ClinicForm.created_at))
        ).all()
        latest = _latest_versions(session, actor.tenant_id)
        return [
            _version_read(form, latest[form.id])
            for form in forms
            if form.id in latest and (include_retired or form.status == "ACTIVE")
        ]


def _publish_version(
    session: Session, actor: Actor, form: ClinicForm, body: ClinicFormWrite, number: int
) -> ClinicFormRead:
    version = ClinicFormVersion(
        tenant_id=actor.tenant_id,
        form_id=form.id,
        version=number,
        title=body.title,
        description=body.description,
        fields=[f.model_dump() for f in body.fields],
        published_by=actor.user_id,
    )
    session.add(version)
    session.flush()
    _record(
        session,
        action=PUBLISH_FORM,
        resource_id=version.id,
        payload={"version": str(number)},
    )
    return _version_read(form, version)


def create_clinic_form(*, actor: Actor, body: ClinicFormWrite) -> ClinicFormRead:
    with _transaction(actor) as session:
        form = ClinicForm(tenant_id=actor.tenant_id, created_by=actor.user_id)
        session.add(form)
        session.flush()
        return _publish_version(session, actor, form, body, 1)


def _clinic_form(
    session: Session, actor: Actor, form_id: uuid.UUID, lock: bool = False
) -> ClinicForm | None:
    statement = select(ClinicForm).where(
        ClinicForm.id == form_id, ClinicForm.tenant_id == actor.tenant_id
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def publish_clinic_form_version(
    *, actor: Actor, form_id: uuid.UUID, body: ClinicFormWrite
) -> ClinicFormRead | Refusal | None:
    """The next version of a form. `None` for absent or another clinic's."""
    with _transaction(actor) as session:
        form = _clinic_form(session, actor, form_id, lock=True)
        if form is None:
            return None
        if form.status != "ACTIVE":
            return Refusal(
                "FORM_RETIRED",
                status.HTTP_409_CONFLICT,
                "A retired form cannot be edited",
            )
        latest = _latest_versions(session, actor.tenant_id)[form.id]
        return _publish_version(session, actor, form, body, latest.version + 1)


def retire_clinic_form(*, actor: Actor, form_id: uuid.UUID) -> ClinicFormRead | None:
    """Stop offering a form. Its responses stay; it can no longer be filled in."""
    with _transaction(actor) as session:
        form = _clinic_form(session, actor, form_id, lock=True)
        if form is None:
            return None
        if form.status == "ACTIVE":
            form.status = "RETIRED"
            session.add(form)
            session.flush()
            _record(session, action=RETIRE_FORM, resource_id=form.id)
        return _version_read(form, _latest_versions(session, actor.tenant_id)[form.id])


def _checked_answers(
    fields: list[ClinicFormField], answers: dict[str, object]
) -> dict[str, object] | str:
    """The answers, normalised, or a refusal message naming the field (never the value)."""
    known = {f.id: f for f in fields}
    unknown = sorted(set(answers) - set(known))
    if unknown:
        return f"Unknown field: {unknown[0]}"
    checked: dict[str, object] = {}
    for field in fields:
        value = answers.get(field.id)
        if value is None or value == "":
            if field.required:
                return f"{field.label} is required"
            continue
        if field.type in _TEXT_LIMITS:
            if not isinstance(value, str) or len(value) > _TEXT_LIMITS[field.type]:
                return f"{field.label}: text of at most {_TEXT_LIMITS[field.type]} characters"
        elif field.type == "CHOICE":
            if value not in field.options:
                return f"{field.label}: choose one of the options"
        elif field.type == "SCALE":
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not (
                    cast(int, field.scale_min) <= value <= cast(int, field.scale_max)
                )
            ):
                return f"{field.label}: a whole number from {field.scale_min} to {field.scale_max}"
        elif field.type == "DATE":
            try:
                date.fromisoformat(cast(str, value))
            except TypeError, ValueError:
                return f"{field.label}: a date (YYYY-MM-DD)"
        elif field.type == "YES_NO":
            if not isinstance(value, bool):
                return f"{field.label}: yes or no"
        checked[field.id] = value
    return checked


def _clinic_response_read(
    row: ClinicFormResponse, version: ClinicFormVersion, corrected_by: uuid.UUID | None
) -> ClinicFormResponseRead:
    decrypted = field_crypto.decrypt(
        row.answers, tenant_id=row.tenant_id, kind=_CLINIC_ANSWERS_KIND
    )
    raw: dict[str, object] = json.loads(decrypted) if decrypted else {}
    answers: dict[str, AnswerValue] = {
        k: v for k, v in raw.items() if isinstance(v, str | int | bool)
    }
    return ClinicFormResponseRead(
        id=row.id,
        patient_id=row.patient_id,
        form_id=version.form_id,
        form_version_id=version.id,
        version=version.version,
        title=version.title,
        fields=[ClinicFormField.model_validate(f) for f in version.fields],
        answers=answers,
        entered_by=row.entered_by,
        corrects_id=row.corrects_id,
        corrected_by_id=corrected_by,
        created_at=row.created_at,
    )


def record_clinic_response(
    *, actor: Actor, patient_id: uuid.UUID, body: ClinicFormResponseCreate
) -> ClinicFormResponseRead | Refusal:
    access = _access(actor, patient_id, WRITE, CREATE)
    if isinstance(access, Refusal):
        return access
    with _transaction(actor) as session:
        version = session.exec(
            select(ClinicFormVersion).where(
                ClinicFormVersion.id == body.form_version_id,
                ClinicFormVersion.tenant_id == actor.tenant_id,
            )
        ).first()
        form = (
            None if version is None else _clinic_form(session, actor, version.form_id)
        )
        if version is None or form is None:
            return Refusal(
                "FORM_NOT_FOUND",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Choose one of the clinic's forms",
            )
        if (
            form.status != "ACTIVE"
            or _latest_versions(session, actor.tenant_id)[form.id].id != version.id
        ):
            return Refusal(
                "FORM_VERSION_STALE",
                status.HTTP_409_CONFLICT,
                "This form has changed or been retired; reload it and fill it in again",
            )
        fields = [ClinicFormField.model_validate(f) for f in version.fields]
        checked = _checked_answers(fields, dict(body.answers))
        if isinstance(checked, str):
            return Refusal(
                "INVALID_ANSWERS", status.HTTP_422_UNPROCESSABLE_CONTENT, checked
            )
        if body.corrects_id is not None:
            original = session.exec(
                select(ClinicFormResponse).where(
                    ClinicFormResponse.id == body.corrects_id,
                    ClinicFormResponse.tenant_id == actor.tenant_id,
                    ClinicFormResponse.patient_id == patient_id,
                )
            ).first()
            if original is None:
                return Refusal(
                    "CORRECTED_RESPONSE_NOT_FOUND",
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "A correction must name an earlier response of this patient",
                )
        row = ClinicFormResponse(
            tenant_id=actor.tenant_id,
            patient_id=patient_id,
            form_version_id=version.id,
            answers=field_crypto.encrypt(
                json.dumps(checked),
                tenant_id=actor.tenant_id,
                kind=_CLINIC_ANSWERS_KIND,
            ),
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
        session.refresh(row)
        return _clinic_response_read(row, version, None)


def _clinic_responses(
    session: Session, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> list[ClinicFormResponseRead]:
    rows = list(
        session.exec(
            select(ClinicFormResponse)
            .where(
                ClinicFormResponse.tenant_id == tenant_id,
                ClinicFormResponse.patient_id == patient_id,
            )
            .order_by(
                col(ClinicFormResponse.created_at).desc(), col(ClinicFormResponse.id)
            )
            .limit(200)
        ).all()
    )
    if not rows:
        return []
    versions = {
        v.id: v
        for v in session.exec(
            select(ClinicFormVersion).where(
                ClinicFormVersion.tenant_id == tenant_id,
                col(ClinicFormVersion.id).in_({r.form_version_id for r in rows}),
            )
        ).all()
    }
    corrected_by = {r.corrects_id: r.id for r in rows if r.corrects_id is not None}
    return [
        _clinic_response_read(r, versions[r.form_version_id], corrected_by.get(r.id))
        for r in rows
    ]
