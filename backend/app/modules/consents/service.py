"""The consent library (docs3 Phase 6 feature 06, R1-R4; decision D22).

* **Which text is current.** For each kind, the clinic's latest published `consent_versions` row, or
  the platform default when the clinic has published none (R1). Every reader goes through
  `current_documents`, so the public application, the in-clinic record and the patient's status all
  agree on what "current" means.
* **Nothing is assumed.** A patient's consent is `CURRENT` only when its version label and text hash
  match the current document; after a new version is published it reads `NEEDS_RECONSENT` until the
  patient agrees again (R3). A withdrawal is its own append-only record and wins until a later consent
  (R4).
* **Access.** Publishing needs `tenant:configure` (as SOPs do). Reading a patient's consents needs
  `patient:read`; recording or withdrawing needs `patient:update`; both under the care-relationship
  rule (D-007). A patient of another clinic is `404`. Every decision is audited with ids only.

Not built here: checking consent text against the blocked-terms list (R5) waits for the comms
guardrail (feature 07).
"""

import hashlib
import uuid
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

from fastapi import status
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.consents.documents import PLATFORM_CONSENTS, ConsentDocument
from app.modules.consents.models import (
    CONSENT_KINDS,
    ConsentVersion,
    ConsentWithdrawal,
    PatientConsent,
)
from app.modules.consents.schemas import (
    ConsentDocumentRead,
    ConsentEvent,
    ConsentKind,
    ConsentKindLibrary,
    ConsentLibrary,
    ConsentStatus,
    KindStatus,
    PatientConsentStatus,
)
from app.modules.patients import service as patients_service
from app.modules.users_roles.policy import Actor, Decision

CONFIGURE: Final[str] = "tenant:configure"
PATIENT_READ: Final[str] = "patient:read"
PATIENT_UPDATE: Final[str] = "patient:update"
PUBLISH: Final[str] = "consent.publish"
RECORD: Final[str] = "consent.record"
WITHDRAW: Final[str] = "consent.withdraw"
READ: Final[str] = "patient.read"

# What not holding each consent means, for staff (D22). Shown, not enforced: enforcement belongs to the
# features it would stop (booking types, treatment), and is a later decision.
STOPS: Final[dict[str, str]] = {
    "PRIVACY": "Without it the clinic should not collect more of the patient's information. Discuss "
    "with the practice owner before continuing care.",
    "TELEHEALTH": "Book in-person consultations only.",
    "TREATMENT": "No new treatment or prescription until consent is given again.",
}


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


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def _label(version: int) -> str:
    return f"clinic-{version}"


def _document(row: ConsentVersion) -> ConsentDocument:
    return ConsentDocument(
        kind=row.kind, version=_label(row.version), title=row.title, body=row.body
    )


# -- which text is current (every reader goes through here) -----------------------------------------


def _latest_versions(
    session: Session, tenant_id: uuid.UUID
) -> dict[str, ConsentVersion]:
    rows = session.exec(
        select(ConsentVersion)
        .where(ConsentVersion.tenant_id == tenant_id)
        .order_by(col(ConsentVersion.kind), col(ConsentVersion.version).desc())
    ).all()
    latest: dict[str, ConsentVersion] = {}
    for row in rows:
        latest.setdefault(row.kind, row)
    return latest


def current_documents(
    session: Session, *, tenant_id: uuid.UUID
) -> dict[str, ConsentDocument]:
    """The document each kind offers today: the clinic's latest version, else the platform default."""
    latest = _latest_versions(session, tenant_id)
    return {
        kind: _document(latest[kind]) if kind in latest else PLATFORM_CONSENTS[kind]
        for kind in CONSENT_KINDS
    }


def document_for(
    session: Session, *, tenant_id: uuid.UUID, kind: str, version: str
) -> ConsentDocument | None:
    """Any version this clinic has offered, by its label, so a record keeps the exact text hash."""
    platform = PLATFORM_CONSENTS.get(kind)
    if platform is not None and platform.version == version:
        return platform
    if version.startswith("clinic-") and version[7:].isdigit():
        row = session.exec(
            select(ConsentVersion).where(
                ConsentVersion.tenant_id == tenant_id,
                ConsentVersion.kind == kind,
                ConsentVersion.version == int(version[7:]),
            )
        ).first()
        return _document(row) if row is not None else None
    return None


def file_application_consents(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    given: Sequence[dict[str, str]],
    signed_at: datetime,
    application_id: uuid.UUID,
) -> None:
    """File the consents an accepted online application gave, on the caller's transaction."""
    for item in given:
        document = document_for(
            session, tenant_id=tenant_id, kind=item["kind"], version=item["version"]
        )
        session.add(
            PatientConsent(
                tenant_id=tenant_id,
                patient_id=patient_id,
                kind=item["kind"],
                version=item["version"],
                text_sha256=document.sha256 if document is not None else "",
                method="ONLINE_APPLICATION",
                signed_at=signed_at,
                application_id=application_id,
            )
        )


# -- the library (Settings) -----------------------------------------------------------------------


def _read(document: ConsentDocument, row: ConsentVersion | None) -> ConsentDocumentRead:
    return ConsentDocumentRead(
        kind=cast(ConsentKind, document.kind),
        version=document.version,
        title=document.title,
        body=document.body,
        source="CLINIC" if row is not None else "PLATFORM",
        published_at=row.published_at if row is not None else None,
    )


def _needing_reconsent(
    session: Session, tenant_id: uuid.UUID, kind: str, current: ConsentDocument
) -> int:
    """Patients whose latest consent of this kind is not the current text (and not withdrawn)."""
    statuses = _statuses_for_tenant(session, tenant_id, kind, current)
    return sum(1 for value in statuses.values() if value == "NEEDS_RECONSENT")


def library(*, actor: Actor) -> ConsentLibrary:
    with _transaction(actor) as session:
        rows = session.exec(
            select(ConsentVersion)
            .where(ConsentVersion.tenant_id == actor.tenant_id)
            .order_by(col(ConsentVersion.kind), col(ConsentVersion.version).desc())
        ).all()
        by_kind: dict[str, list[ConsentVersion]] = {}
        for row in rows:
            by_kind.setdefault(row.kind, []).append(row)
        current = current_documents(session, tenant_id=actor.tenant_id)
        kinds: list[ConsentKindLibrary] = []
        for kind in CONSENT_KINDS:
            versions = by_kind.get(kind, [])
            kinds.append(
                ConsentKindLibrary(
                    kind=cast(ConsentKind, kind),
                    current=_read(current[kind], versions[0] if versions else None),
                    clinic_versions=[_read(_document(r), r) for r in versions],
                    patients_needing_reconsent=_needing_reconsent(
                        session, actor.tenant_id, kind, current[kind]
                    ),
                )
            )
        return ConsentLibrary(kinds=kinds)


def publish(*, actor: Actor, kind: str, title: str, body: str) -> ConsentDocumentRead:
    """Publish the clinic's next version of a consent (R1, R2). Patients on an older text now need to
    consent again (R3); nothing is assumed."""
    with _transaction(actor) as session:
        latest = session.exec(
            select(func.max(ConsentVersion.version)).where(
                ConsentVersion.tenant_id == actor.tenant_id, ConsentVersion.kind == kind
            )
        ).one()
        row = ConsentVersion(
            tenant_id=actor.tenant_id,
            kind=kind,
            version=(latest or 0) + 1,
            title=title,
            body=body,
            body_sha256=_sha256(body),
            published_by=actor.user_id,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            action=PUBLISH,
            resource_id=row.id,
            payload={"kind": kind, "version": _label(row.version)},
        )
        return _read(_document(row), row)


# -- a patient's consents ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Event:
    kind: str
    patient_id: uuid.UUID
    at: datetime
    consent: PatientConsent | None
    withdrawal: ConsentWithdrawal | None


def _events(
    session: Session,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID | None,
    kind: str | None = None,
) -> list[_Event]:
    consents_q = select(PatientConsent).where(PatientConsent.tenant_id == tenant_id)
    withdrawals_q = select(ConsentWithdrawal).where(
        ConsentWithdrawal.tenant_id == tenant_id
    )
    if patient_id is not None:
        consents_q = consents_q.where(PatientConsent.patient_id == patient_id)
        withdrawals_q = withdrawals_q.where(ConsentWithdrawal.patient_id == patient_id)
    if kind is not None:
        consents_q = consents_q.where(PatientConsent.kind == kind)
        withdrawals_q = withdrawals_q.where(ConsentWithdrawal.kind == kind)
    events = [
        _Event(c.kind, c.patient_id, c.signed_at, c, None)
        for c in session.exec(consents_q).all()
    ]
    events += [
        _Event(w.kind, w.patient_id, w.withdrawn_at, None, w)
        for w in session.exec(withdrawals_q).all()
    ]
    # Newest first; at the same instant a withdrawal is later than the consent it withdraws.
    events.sort(key=lambda e: (e.at, e.withdrawal is not None), reverse=True)
    return events


def _status(latest: _Event | None, current: ConsentDocument) -> ConsentStatus:
    if latest is None:
        return "NOT_GIVEN"
    if latest.withdrawal is not None:
        return "WITHDRAWN"
    consent = latest.consent
    assert consent is not None
    if consent.version == current.version and consent.text_sha256 == current.sha256:
        return "CURRENT"
    return "NEEDS_RECONSENT"


def _statuses_for_tenant(
    session: Session, tenant_id: uuid.UUID, kind: str, current: ConsentDocument
) -> dict[uuid.UUID, ConsentStatus]:
    latest: dict[uuid.UUID, _Event] = {}
    for event in _events(session, tenant_id, None, kind):
        latest.setdefault(event.patient_id, event)
    return {patient: _status(event, current) for patient, event in latest.items()}


def _access(
    actor: Actor, patient_id: uuid.UUID, permission: str, action: str
) -> Refusal | None:
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
    return None


def _patient_status(
    session: Session, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> PatientConsentStatus:
    current = current_documents(session, tenant_id=tenant_id)
    events = _events(session, tenant_id, patient_id)
    kinds: list[KindStatus] = []
    for kind in CONSENT_KINDS:
        of_kind = [e for e in events if e.kind == kind]
        latest = of_kind[0] if of_kind else None
        last_consent = next((e.consent for e in of_kind if e.consent is not None), None)
        kinds.append(
            KindStatus(
                kind=cast(ConsentKind, kind),
                title=current[kind].title,
                status=_status(latest, current[kind]),
                current_version=current[kind].version,
                current_body=current[kind].body,
                signed_version=last_consent.version if last_consent else None,
                signed_at=last_consent.signed_at if last_consent else None,
                withdrawn_at=latest.withdrawal.withdrawn_at
                if latest is not None and latest.withdrawal is not None
                else None,
                stops=STOPS[kind],
            )
        )
    history: list[ConsentEvent] = []
    for event in events:
        if event.consent is not None:
            document = document_for(
                session,
                tenant_id=tenant_id,
                kind=event.kind,
                version=event.consent.version,
            )
            history.append(
                ConsentEvent(
                    kind=cast(ConsentKind, event.kind),
                    event="CONSENTED",
                    version=event.consent.version,
                    title=document.title if document else None,
                    method=event.consent.method,
                    at=event.at,
                    recorded_by=event.consent.recorded_by,
                )
            )
        elif event.withdrawal is not None:
            history.append(
                ConsentEvent(
                    kind=cast(ConsentKind, event.kind),
                    event="WITHDRAWN",
                    version=None,
                    title=None,
                    method=event.withdrawal.method,
                    at=event.at,
                    recorded_by=event.withdrawal.recorded_by,
                )
            )
    return PatientConsentStatus(kinds=kinds, history=history)


def patient_status(
    *, actor: Actor, patient_id: uuid.UUID
) -> PatientConsentStatus | Refusal:
    refused = _access(actor, patient_id, PATIENT_READ, READ)
    if refused is not None:
        return refused
    with _transaction(actor) as session:
        result = _patient_status(session, actor.tenant_id, patient_id)
        _record(
            session,
            action=READ,
            resource_id=patient_id,
            payload={
                "query_filters": ["CONSENTS"],
                "result_count": len(result.history),
            },
        )
        return result


def record_consent(
    *, actor: Actor, patient_id: uuid.UUID, kind: str, version: str
) -> PatientConsentStatus | Refusal:
    """A consent given in clinic, at the version currently offered (R2, R3)."""
    refused = _access(actor, patient_id, PATIENT_UPDATE, RECORD)
    if refused is not None:
        return refused
    with _transaction(actor) as session:
        current = current_documents(session, tenant_id=actor.tenant_id)[kind]
        if version != current.version:
            return Refusal(
                "CONSENT_VERSION_STALE",
                status.HTTP_409_CONFLICT,
                "The consent has a newer version. Show the patient the current text and record again.",
            )
        row = PatientConsent(
            tenant_id=actor.tenant_id,
            patient_id=patient_id,
            kind=kind,
            version=current.version,
            text_sha256=current.sha256,
            method="IN_CLINIC",
            signed_at=datetime.now(UTC),
            recorded_by=actor.user_id,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            action=RECORD,
            resource_id=row.id,
            payload={"patient_id": str(patient_id)},
        )
        return _patient_status(session, actor.tenant_id, patient_id)


def withdraw(
    *, actor: Actor, patient_id: uuid.UUID, kind: str, method: str
) -> PatientConsentStatus | Refusal:
    """Record a withdrawal, effective now (R4). Only a consent the patient holds can be withdrawn."""
    refused = _access(actor, patient_id, PATIENT_UPDATE, WITHDRAW)
    if refused is not None:
        return refused
    with _transaction(actor) as session:
        current = current_documents(session, tenant_id=actor.tenant_id)[kind]
        events = _events(session, actor.tenant_id, patient_id, kind)
        if _status(events[0] if events else None, current) in (
            "NOT_GIVEN",
            "WITHDRAWN",
        ):
            return Refusal(
                "NOTHING_TO_WITHDRAW",
                status.HTTP_409_CONFLICT,
                "The patient does not hold this consent",
            )
        row = ConsentWithdrawal(
            tenant_id=actor.tenant_id,
            patient_id=patient_id,
            kind=kind,
            method=method,
            recorded_by=actor.user_id,
        )
        session.add(row)
        session.flush()
        _record(
            session,
            action=WITHDRAW,
            resource_id=row.id,
            payload={"patient_id": str(patient_id)},
        )
        return _patient_status(session, actor.tenant_id, patient_id)
