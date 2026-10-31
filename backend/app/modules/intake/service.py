"""Patient intake (docs3 feature 03; Platform Manual §5.1, §5.4, §8.1, §12.3).

The public application is recorded on the booking's own transaction (`app.modules.appointments`
`public_book`), so the patient, the held booking and the application commit together or not at all.
The clinic then works the queue: accepting files the consents, the declaration, the pharmacy and (on a
record the application created) the submitted details; rejecting cancels the held booking and archives
a record the application created.

**The answers are HIGHLY_SENSITIVE.** They are never logged and never audited: every audit event here
carries ids, codes and statuses only. They are read through the queue (`patient:read`) and the doctor's
briefing (`clinical_record:read` under the treating-relationship rule, D-007).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlmodel import Session, col, select

from app.core.db import tenant_transaction
from app.modules.audit import service as audit
from app.modules.intake.consents import CONSENT_DOCUMENTS, CURRENT_CONSENTS
from app.modules.intake.models import IntakeApplication, PatientConsent, Pharmacy
from app.modules.intake.schemas import (
    ApplicationCard,
    ApplicationDetail,
    ConsentRecord,
    IntakeApplicationIn,
    IntakeBriefing,
    IntakeForm,
    PharmacyCreate,
    PharmacyRead,
    PublicConsent,
    PublicPharmacy,
    RejectBody,
)
from app.modules.patients import service as patients
from app.modules.users_roles.policy import Actor, Decision

APPLICATION_SUBMIT: Final = "intake.application_submit"
APPLICATION_READ: Final = "intake.application_read"
APPLICATION_DECIDE: Final = "intake.application_decide"
PHARMACY_CREATE: Final = "pharmacy.create"

DECLARATION_MISMATCH: Final = "DECLARATION_MISMATCH"
CONSENT_VERSION_STALE: Final = "CONSENT_VERSION_STALE"
PHARMACY_NOT_FOUND: Final = "PHARMACY_NOT_FOUND"
ALREADY_DECIDED: Final = "ALREADY_DECIDED"
APPLICATION_NOT_FOUND: Final = "APPLICATION_NOT_FOUND"

# The flags the queue shows, computed by the server from the answers.
_SAFETY_FLAGS: Final[dict[str, str]] = {
    "psychosis_history": "PSYCHOSIS_HISTORY",
    "pregnant_or_breastfeeding": "PREGNANT_OR_BREASTFEEDING",
    "heart_condition": "HEART_CONDITION",
    "substance_dependence": "SUBSTANCE_DEPENDENCE",
}


class IntakeRefused(Exception):  # noqa: N818 - the module's refusal, as `AppointmentRefused`
    """A refusal the caller answers with `status_code` and `{code, message}`."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message


def _normalised(name: str) -> str:
    return " ".join(name.lower().split())


# -- the public form -------------------------------------------------------------------------------


def intake_form(session: Session, *, tenant_id: uuid.UUID) -> IntakeForm:
    """The consents at their current versions and the clinic's partner pharmacies (name, suburb)."""
    partners = session.exec(
        select(Pharmacy)
        .where(col(Pharmacy.tenant_id) == tenant_id, col(Pharmacy.is_partner).is_(True))
        .order_by(col(Pharmacy.name))
    ).all()
    return IntakeForm(
        consents=[
            PublicConsent(kind=d.kind, version=d.version, title=d.title, body=d.body)
            for d in CONSENT_DOCUMENTS
        ],
        partner_pharmacies=[
            PublicPharmacy(id=p.id, name=p.name, suburb=p.suburb) for p in partners
        ],
    )


def check_application(
    application: IntakeApplicationIn, *, given_name: str, family_name: str
) -> None:
    """Refuse an application before anything is written (manual §5.1 steps 4 and 6).

    Every consent must be given at the version currently shown, and the typed declaration must be
    the applicant's own name.
    """
    expected = _normalised(f"{given_name} {family_name}")
    if _normalised(application.declaration_name) != expected:
        raise IntakeRefused(
            422,
            DECLARATION_MISMATCH,
            "Type your full name exactly as you entered it on the first step.",
        )
    given = {c.kind: c.version for c in application.consents}
    current = {kind: d.version for kind, d in CURRENT_CONSENTS.items()}
    if given != current:
        raise IntakeRefused(
            422,
            CONSENT_VERSION_STALE,
            "The consent documents have changed. Reload the page and read them again.",
        )


def _flags(application: IntakeApplicationIn) -> list[str]:
    safety = application.safety.model_dump()
    flags = [flag for key, flag in _SAFETY_FLAGS.items() if safety[key]]
    if not application.tried_conventional:
        flags.append("NO_CONVENTIONAL_THERAPY")
    if not application.cannabis_used_before:
        flags.append("CANNABIS_NAIVE")
    return flags


def record_application(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    created_patient: bool,
    appointment_id: uuid.UUID | None,
    application: IntakeApplicationIn,
    source_ip: str | None,
) -> uuid.UUID:
    """Store a checked application on the booking's transaction and audit it (ids only)."""
    if application.pharmacy_id is not None:
        partner = session.exec(
            select(Pharmacy.id).where(
                col(Pharmacy.tenant_id) == tenant_id,
                col(Pharmacy.id) == application.pharmacy_id,
                col(Pharmacy.is_partner).is_(True),
            )
        ).first()
        if partner is None:
            raise IntakeRefused(
                422, PHARMACY_NOT_FOUND, "Choose a pharmacy from the list."
            )
    answers = application.model_dump(
        mode="json",
        exclude={"consents", "pharmacy_id", "own_pharmacy", "declaration_name"},
    )
    row = IntakeApplication(
        tenant_id=tenant_id,
        patient_id=patient_id,
        appointment_id=appointment_id,
        created_patient=created_patient,
        answers=answers,
        flags=_flags(application),
        consents=[c.model_dump() for c in application.consents],
        pharmacy_id=application.pharmacy_id,
        own_pharmacy=(
            application.own_pharmacy.model_dump(mode="json")
            if application.own_pharmacy is not None
            else None
        ),
        declaration_name=application.declaration_name,
        declared_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=APPLICATION_SUBMIT,
            result="SUCCESS",
            resource_id=row.id,
            source_ip=source_ip,
            payload={"patient_id": str(patient_id)},
        ),
    )
    return row.id


# -- the queue -------------------------------------------------------------------------------------


def _transaction(actor: Actor) -> Any:  # noqa: ANN401 - the helper's context manager
    return tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id, actor_role=actor.actor_role
    )


def _starts(
    session: Session, *, tenant_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    from app.modules.appointments import (
        service as appointments,  # noqa: PLC0415 - one-way
    )

    return appointments.start_times(session, tenant_id=tenant_id, appointment_ids=ids)


def _cards(
    session: Session, *, tenant_id: uuid.UUID, rows: list[IntakeApplication]
) -> list[ApplicationCard]:
    people = patients.summaries(
        session, tenant_id=tenant_id, patient_ids=[r.patient_id for r in rows]
    )
    starts = _starts(
        session,
        tenant_id=tenant_id,
        ids=[r.appointment_id for r in rows if r.appointment_id is not None],
    )
    cards = []
    for row in rows:
        person = people.get(row.patient_id)
        if person is None:
            continue
        cards.append(
            ApplicationCard(
                id=row.id,
                status=row.status,
                created_at=row.created_at,
                patient_id=row.patient_id,
                patient_name=person.name,
                date_of_birth=person.date_of_birth,
                matched_existing=not row.created_patient,
                flags=list(row.flags),
                appointment_starts_at=(
                    starts.get(row.appointment_id) if row.appointment_id else None
                ),
            )
        )
    return cards


def list_applications(*, actor: Actor, status: str) -> list[ApplicationCard]:
    """The queue, oldest first: answers are not part of a card."""
    with _transaction(actor) as session:
        rows = list(
            session.exec(
                select(IntakeApplication)
                .where(
                    col(IntakeApplication.tenant_id) == actor.tenant_id,
                    col(IntakeApplication.status) == status,
                )
                .order_by(col(IntakeApplication.created_at))
                .limit(100)
            ).all()
        )
        return _cards(session, tenant_id=actor.tenant_id, rows=rows)


def _application(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    lock: bool = False,
) -> IntakeApplication | None:
    statement = select(IntakeApplication).where(
        col(IntakeApplication.tenant_id) == tenant_id,
        col(IntakeApplication.id) == application_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).first()


def _pharmacy_view(
    session: Session, row: IntakeApplication
) -> dict[str, object] | None:
    if row.pharmacy_id is not None:
        pharmacy = session.get(Pharmacy, row.pharmacy_id)
        return (
            None
            if pharmacy is None
            else {
                "kind": "PARTNER",
                "id": str(pharmacy.id),
                "name": pharmacy.name,
                "suburb": pharmacy.suburb,
            }
        )
    if row.own_pharmacy is not None:
        return {"kind": "OWN", **row.own_pharmacy}
    return None


def read_application(
    *, actor: Actor, application_id: uuid.UUID
) -> ApplicationDetail | None:
    """One application in full. Audited as a read of the applicant's record (ids only)."""
    with _transaction(actor) as session:
        row = _application(
            session, tenant_id=actor.tenant_id, application_id=application_id
        )
        if row is None:
            return None
        cards = _cards(session, tenant_id=actor.tenant_id, rows=[row])
        if not cards:
            return None
        card = cards[0]
        audit.record(
            session,
            audit.AuditEvent(
                action=APPLICATION_READ,
                result="SUCCESS",
                resource_id=row.id,
                payload={"patient_id": str(row.patient_id)},
            ),
        )
        return ApplicationDetail(
            **card.model_dump(),
            answers=dict(row.answers),
            consents=list(row.consents),
            pharmacy=_pharmacy_view(session, row),
            declaration_name=row.declaration_name,
            declared_at=row.declared_at,
            decided_at=row.decided_at,
            decision_reason_code=row.decision_reason_code,
            decision_note=row.decision_note,
        )


def _decided(
    session: Session, row: IntakeApplication, actor: Actor, *, to_state: str
) -> None:
    row.status = to_state
    row.decided_by = actor.user_id
    row.decided_at = datetime.now(UTC)
    session.add(row)
    session.flush()
    audit.record(
        session,
        audit.AuditEvent(
            action=APPLICATION_DECIDE,
            result="SUCCESS",
            resource_id=row.id,
            reason=row.decision_reason_code,
            payload={"patient_id": str(row.patient_id), "to_state": to_state},
        ),
    )


def accept(*, actor: Actor, application_id: uuid.UUID) -> uuid.UUID:
    """Accept an application (manual §5.4), in one transaction.

    The consents are recorded at the versions signed, the patient's own pharmacy joins the directory,
    the chosen pharmacy becomes the default, a record the application created gets the submitted sex
    and address and becomes `CURRENT`, and the application is `ACCEPTED`. Answers the patient's id.
    """
    with _transaction(actor) as session:
        row = _application(
            session, tenant_id=actor.tenant_id, application_id=application_id, lock=True
        )
        if row is None:
            raise IntakeRefused(404, APPLICATION_NOT_FOUND, "Application not found")
        if row.status != "SUBMITTED":
            raise IntakeRefused(
                409, ALREADY_DECIDED, "This application was already decided."
            )
        pharmacy_id = row.pharmacy_id
        if row.own_pharmacy is not None:
            own = row.own_pharmacy
            pharmacy = Pharmacy(
                tenant_id=actor.tenant_id,
                name=str(own["name"]),
                suburb=str(own["suburb"]),
                address=own.get("address"),
                email=own.get("email"),
                phone=own.get("phone"),
                provider_number=own.get("provider_number"),
                created_from="APPLICATION",
            )
            session.add(pharmacy)
            session.flush()
            pharmacy_id = pharmacy.id
            audit.record(
                session,
                audit.AuditEvent(
                    action=PHARMACY_CREATE, result="SUCCESS", resource_id=pharmacy.id
                ),
            )
        for given in row.consents:
            document = CURRENT_CONSENTS.get(given["kind"])
            session.add(
                PatientConsent(
                    tenant_id=actor.tenant_id,
                    patient_id=row.patient_id,
                    kind=given["kind"],
                    version=given["version"],
                    text_sha256=document.sha256
                    if document and document.version == given["version"]
                    else "",
                    method="ONLINE_APPLICATION",
                    signed_at=row.declared_at,
                    application_id=row.id,
                )
            )
        answers = row.answers
        patients.accept_applicant(
            session,
            tenant_id=actor.tenant_id,
            patient_id=row.patient_id,
            created_by_application=row.created_patient,
            details={
                key: str(answers[key])
                for key in (
                    "sex_at_birth",
                    "address_line",
                    "suburb",
                    "state",
                    "postcode",
                )
            },
            pharmacy_id=pharmacy_id,
        )
        _decided(session, row, actor, to_state="ACCEPTED")
        return row.patient_id


def reject(*, actor: Actor, application_id: uuid.UUID, body: RejectBody) -> None:
    """Reject an application: its held booking is cancelled and a record it created is archived."""
    from app.modules.appointments import (
        service as appointments,  # noqa: PLC0415 - one-way
    )

    with _transaction(actor) as session:
        row = _application(
            session, tenant_id=actor.tenant_id, application_id=application_id, lock=True
        )
        if row is None:
            raise IntakeRefused(404, APPLICATION_NOT_FOUND, "Application not found")
        if row.status != "SUBMITTED":
            raise IntakeRefused(
                409, ALREADY_DECIDED, "This application was already decided."
            )
        if row.appointment_id is not None:
            appointments.cancel_held_booking(
                session, tenant_id=actor.tenant_id, appointment_id=row.appointment_id
            )
        if row.created_patient:
            patients.archive_rejected_applicant(
                session, tenant_id=actor.tenant_id, patient_id=row.patient_id
            )
        row.decision_reason_code = body.reason_code
        row.decision_note = body.note
        _decided(session, row, actor, to_state="REJECTED")


# -- on the patient record -------------------------------------------------------------------------


@dataclass(frozen=True)
class Refused:
    """A patient-level refusal from the patients facade: `404`, or the policy's decision."""

    status_code: int
    decision: Decision | None = None


def _patient_reachable(
    actor: Actor, patient_id: uuid.UUID, permission: str
) -> Refused | None:
    resolved = patients.patient_access(
        actor=actor, patient_id=patient_id, permission=permission
    )
    if resolved.patient is None:
        return Refused(404)
    if resolved.access is not None and not resolved.access.allowed:
        return Refused(resolved.access.decision.status_code, resolved.access.decision)
    return None


def briefing(*, actor: Actor, patient_id: uuid.UUID) -> IntakeBriefing | Refused | None:
    """The doctor's briefing from the patient's latest application (manual §5.4). Audited."""
    refused = _patient_reachable(actor, patient_id, "clinical_record:read")
    if refused is not None:
        return refused
    with _transaction(actor) as session:
        row = session.exec(
            select(IntakeApplication)
            .where(
                col(IntakeApplication.tenant_id) == actor.tenant_id,
                col(IntakeApplication.patient_id) == patient_id,
                col(IntakeApplication.status) != "REJECTED",
            )
            .order_by(col(IntakeApplication.created_at).desc())
            .limit(1)
        ).first()
        if row is None:
            return None
        audit.record(
            session,
            audit.AuditEvent(
                action=APPLICATION_READ,
                result="SUCCESS",
                resource_id=row.id,
                payload={"patient_id": str(patient_id)},
            ),
        )
        a = row.answers
        return IntakeBriefing(
            application_id=row.id,
            submitted_at=row.created_at,
            primary_condition=str(a["primary_condition"]),
            other_conditions=list(a.get("other_conditions", [])),
            tried_conventional=bool(a["tried_conventional"]),
            conventional_detail=str(a.get("conventional_detail", "")),
            current_medicines=str(a.get("current_medicines", "")),
            safety_flags=[f for f in row.flags if f in _SAFETY_FLAGS.values()],
            cannabis_used_before=bool(a["cannabis_used_before"]),
            cannabis_forms=list(a.get("cannabis_forms", [])),
            cannabis_duration=a.get("cannabis_duration"),
            side_effects=str(a.get("side_effects", "")),
            what_helped=str(a.get("what_helped", "")),
            pharmacy=_pharmacy_view(session, row),
            declaration_name=row.declaration_name,
            declared_at=row.declared_at,
        )


def consents(*, actor: Actor, patient_id: uuid.UUID) -> list[ConsentRecord] | Refused:
    """Which version of each consent the patient signed, and whether it is still current."""
    refused = _patient_reachable(actor, patient_id, "patient:read")
    if refused is not None:
        return refused
    with _transaction(actor) as session:
        rows = session.exec(
            select(PatientConsent)
            .where(
                col(PatientConsent.tenant_id) == actor.tenant_id,
                col(PatientConsent.patient_id) == patient_id,
            )
            .order_by(col(PatientConsent.signed_at).desc())
        ).all()
        return [
            ConsentRecord(
                kind=r.kind,
                version=r.version,
                title=CURRENT_CONSENTS[r.kind].title
                if r.kind in CURRENT_CONSENTS
                else r.kind,
                method=r.method,
                signed_at=r.signed_at,
                current=r.kind in CURRENT_CONSENTS
                and CURRENT_CONSENTS[r.kind].version == r.version,
            )
            for r in rows
        ]


# -- the pharmacy directory ------------------------------------------------------------------------


def list_pharmacies(*, actor: Actor) -> list[PharmacyRead]:
    with _transaction(actor) as session:
        rows = session.exec(
            select(Pharmacy)
            .where(col(Pharmacy.tenant_id) == actor.tenant_id)
            .order_by(col(Pharmacy.name))
        ).all()
        return [PharmacyRead.model_validate(r) for r in rows]


def create_pharmacy(*, actor: Actor, body: PharmacyCreate) -> PharmacyRead:
    with _transaction(actor) as session:
        pharmacy = Pharmacy(tenant_id=actor.tenant_id, **body.model_dump(mode="json"))
        session.add(pharmacy)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=PHARMACY_CREATE, result="SUCCESS", resource_id=pharmacy.id
            ),
        )
        session.refresh(pharmacy)
        return PharmacyRead.model_validate(pharmacy)
