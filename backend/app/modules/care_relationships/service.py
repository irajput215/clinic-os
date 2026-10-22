"""Care relationships service facade - the treating-relationship rule's data source, and its upkeep.

Design: the rule is `hasActiveCareRelationship(actor, patient_id)` in the central policy layer
(`docs/features/06-clinical-records/03-design.md`, "Treating-relationship check";
`docs/features/05-patients/03-design.md`, "Treating-relationship rule"), which reads
`care_relationships(tenant_id, practitioner_id, patient_id, clinic_id, active_from, active_to, source)`
under the same row-level security policy as the request. It is **never** inferred from clinic
membership and **never** widened to the tenant (`docs/features/03-users-and-roles/04-threat-model.md`
T-03.1; `05-patients/04-threat-model.md` T-05.9). Task T1-34; decision D-007.

## How a route applies the rule (one statement, no extra round trip)

`relationship_id(...)` is a scalar subquery: the id of the actor's active relationship with a patient,
or `NULL`. A route selects it **beside the row it is already loading** (the patient, the clinical
record, the prescription), so the relationship rides in the route's first statement under the same
transaction, the same tenant context and the same RLS policy as the read itself:

    select(Patient, care.relationship_id(tenant_id=..., practitioner_id=..., patient_id=Patient.id))

`patient_access(actor, permission, patient_id=..., care_relationship_id=...)` then asks the central
policy layer, which refuses `403 AUTHZ_CARE_RELATIONSHIP_DENIED` when the permission is held only
through a relationship-bound grant (`catalog.CARE_RELATIONSHIP_SCOPED_GRANTS`) and no relationship was
found. The answer carries what the audit envelope records: `care_relationship_id` and `purpose`.

## The interval

`active_from <= now() AND (active_to IS NULL OR active_to > now())` - half-open `[active_from,
active_to)`, the boundary D-006 fixes as the interim fail-safe. `now()` is the transaction's own clock,
so the rule and the read it guards agree on "now". An ended relationship (`active_to <= now`) and a
future-dated one (`active_from > now`) are both **inactive**. If more than one interval is active for
the same practitioner and patient, the most recent `active_from` wins, deterministically.

## The purpose (D-007, interim)

The design asks every patient read to record a `purpose` and names no vocabulary; open-questions.md
records the purpose-code question with the Privacy Officer. Until it is settled the purpose is
**derived by the server, never supplied by the client**: `TREATMENT` when an active care relationship
authorised the read, and `PRACTICE_ADMINISTRATION` when an unconditional grant did (an owner,
administrator or authorised prescriber with no relationship of their own).

## Who maintains the table (D-007, interim)

The source of truth is OPEN (open-questions.md C13; `05-patients` OPEN-4). The interim is the
narrowest one that does not infer access from anything: a relationship exists only because a person
whose **own** access to the patient is not relationship-bound (`patient:update` held unconditionally:
practice owner, authorised prescriber, administrator) recorded it, naming an active practitioner of the
same organisation, and it ends when such a person ends it. Both are audited on the same transaction
(`care_relationship.create`, `care_relationship.end`). Nothing creates one implicitly: not a booking,
not a consult note, not clinic membership.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import ColumnElement, ScalarSelect, Select, or_
from sqlalchemy.orm import Mapped
from sqlmodel import Session, col, func, select

from app.core.db import tenant_transaction

# Reached through their service facades (`docs/reference/build-contract.md` §7).
from app.modules.audit import service as audit
from app.modules.care_relationships.models import CareRelationship
from app.modules.care_relationships.schemas import (
    CareRelationshipRead,
    CareTeamMember,
    CareTeamPublic,
)
from app.modules.users_roles import service as users_roles
from app.modules.users_roles.catalog import PRACTITIONER_ROLE_BY_CODE
from app.modules.users_roles.policy import (
    Actor,
    Decision,
    PatientResourceRef,
    can,
)

__all__ = [
    "PRACTICE_ADMINISTRATION",
    "TREATMENT",
    "PatientAccess",
    "active_relationship",
    "end_relationship",
    "has_active_relationship",
    "list_care_team",
    "patient_access",
    "patient_resource",
    "record_relationship",
    "relationship_id",
]

# The two purposes a patient read records (D-007, interim; the vocabulary is the Privacy Officer's).
TREATMENT: Final[str] = "TREATMENT"
PRACTICE_ADMINISTRATION: Final[str] = "PRACTICE_ADMINISTRATION"

# The `source` the interim upkeep writes: a person recorded it. The column is free text by design
# (the vocabulary is OPEN with the Clinical Safety Officer, see the model docstring).
STAFF_RECORDED: Final[str] = "STAFF_RECORDED"

# The two actions the upkeep emits (registered in `app.modules.audit.actions` with D-007).
CARE_RELATIONSHIP_CREATE: Final[str] = "care_relationship.create"
CARE_RELATIONSHIP_END: Final[str] = "care_relationship.end"
# Reading the care team is a read of the patient (`05-patients/05-data-and-audit.md`: "any read").
PATIENT_READ: Final[str] = "patient.read"

# Refusal codes of the upkeep routes.
PATIENT_NOT_FOUND: Final[str] = "PATIENT_NOT_FOUND"
PRACTITIONER_NOT_FOUND: Final[str] = "PRACTITIONER_NOT_FOUND"
ALREADY_IN_CARE_TEAM: Final[str] = "ALREADY_IN_CARE_TEAM"
RELATIONSHIP_NOT_FOUND: Final[str] = "RELATIONSHIP_NOT_FOUND"


def _active(now: ColumnElement[Any]) -> list[ColumnElement[bool]]:
    """The half-open interval `[active_from, active_to)` contains `now`."""
    return [
        col(CareRelationship.active_from) <= now,
        or_(
            col(CareRelationship.active_to).is_(None),
            col(CareRelationship.active_to) > now,
        ),
    ]


def relationship_id(
    *,
    tenant_id: uuid.UUID,
    practitioner_id: uuid.UUID,
    patient_id: uuid.UUID | ColumnElement[uuid.UUID] | Mapped[uuid.UUID],
) -> ScalarSelect[uuid.UUID]:
    """The practitioner's active relationship id with the patient, as a scalar subquery (or `NULL`).

    `patient_id` may be a value or a column of the statement it is embedded in (for a row loaded by its
    own id, `ClinicalRecord.patient_id` say), so the rule costs no statement of its own. The explicit
    `tenant_id` predicate is the second line of defence behind the forced RLS policy, as everywhere.
    """
    return (
        select(col(CareRelationship.id))
        .where(
            col(CareRelationship.tenant_id) == tenant_id,
            col(CareRelationship.practitioner_id) == practitioner_id,
            col(CareRelationship.patient_id) == patient_id,
            *_active(func.now()),
        )
        .order_by(col(CareRelationship.active_from).desc(), col(CareRelationship.id))
        .limit(1)
        .scalar_subquery()
    )


def related_patient_ids(
    *, tenant_id: uuid.UUID, practitioner_id: uuid.UUID
) -> Select[tuple[uuid.UUID]]:
    """The patients this practitioner has an active relationship with, as a subquery for `IN`.

    The filter a relationship-bound reader's list and search apply (`05-patients/03-design.md`,
    "Endpoints": the list is "treating-relationship filtered"), in the list's own statement.
    """
    return select(col(CareRelationship.patient_id)).where(
        col(CareRelationship.tenant_id) == tenant_id,
        col(CareRelationship.practitioner_id) == practitioner_id,
        *_active(func.now()),
    )


def actor_relationship_id(
    actor: Actor, patient_id: uuid.UUID | ColumnElement[uuid.UUID] | Mapped[uuid.UUID]
) -> ScalarSelect[uuid.UUID]:
    """`relationship_id` for the request's own actor, in the actor's own tenant."""
    return relationship_id(
        tenant_id=actor.tenant_id, practitioner_id=actor.user_id, patient_id=patient_id
    )


@dataclass(frozen=True)
class PatientAccess:
    """The policy decision for one patient, and what the audit envelope records about it."""

    decision: Decision
    care_relationship_id: uuid.UUID | None

    @property
    def allowed(self) -> bool:
        return self.decision.allowed

    @property
    def purpose(self) -> str:
        """`TREATMENT` when a relationship authorised the access, else `PRACTICE_ADMINISTRATION`."""
        return (
            TREATMENT
            if self.care_relationship_id is not None
            else PRACTICE_ADMINISTRATION
        )

    @property
    def reason(self) -> str:
        """The refusal's reason code for the audit envelope (`AUTHZ_CARE_RELATIONSHIP_DENIED`...)."""
        return self.decision.code.value

    def audit_payload(self) -> dict[str, str]:
        """`care_relationship_id` (when one exists) and `purpose` - identifiers and codes only."""
        payload = {"purpose": self.purpose}
        if self.care_relationship_id is not None:
            payload["care_relationship_id"] = str(self.care_relationship_id)
        return payload


def patient_access(
    actor: Actor,
    permission: str,
    *,
    patient_id: uuid.UUID,
    care_relationship_id: uuid.UUID | None,
) -> PatientAccess:
    """Decide `permission` on a patient of the actor's own tenant, the relationship already resolved.

    The caller loaded the patient (or the row that names it) under the actor's tenant context, so the
    resource is the actor's tenant: a row from another tenant was never found and is the caller's
    `404`, decided before this is called (R6 - across a tenant boundary the answer stays `404`).
    """
    resource = PatientResourceRef(
        tenant_id=actor.tenant_id,
        patient_id=patient_id,
        care_relationship_id=care_relationship_id,
    )
    return PatientAccess(
        decision=can(actor, permission, resource),
        care_relationship_id=care_relationship_id,
    )


def active_relationship(
    *, actor: Actor, patient_id: uuid.UUID
) -> CareRelationshipRead | None:
    """The actor's active treating relationship with this patient, or `None`.

    `None` means "no active relationship", and it is the same answer whether the patient does not
    exist, belongs to another tenant, or simply has no relationship with this practitioner — none of
    which this function can distinguish, which is what keeps it from leaking existence.
    """
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id
    ) as session:
        found = session.exec(
            select(CareRelationship).where(
                col(CareRelationship.id) == actor_relationship_id(actor, patient_id)
            )
        ).first()
        return None if found is None else CareRelationshipRead.model_validate(found)


def has_active_relationship(*, actor: Actor, patient_id: uuid.UUID) -> bool:
    """The design's `hasActiveCareRelationship(actor, patient_id)`, as a boolean."""
    return active_relationship(actor=actor, patient_id=patient_id) is not None


def patient_resource(*, actor: Actor, patient_id: uuid.UUID) -> PatientResourceRef:
    """The policy-layer resource for a patient, with the relationship resolved on its own read.

    For a caller that has no row of its own to load; a route that loads one embeds `relationship_id`
    in that statement instead and calls `patient_access`.
    """
    relationship = active_relationship(actor=actor, patient_id=patient_id)
    return PatientResourceRef(
        tenant_id=actor.tenant_id,
        patient_id=patient_id,
        care_relationship_id=None if relationship is None else relationship.id,
    )


# -- upkeep (D-007, interim) -----------------------------------------------------------------------


@dataclass(frozen=True)
class Refusal:
    """A decided refusal of an upkeep call; already audited where the design asks for it."""

    status_code: int
    code: str
    message: str


def _transaction(actor: Actor, source_ip: str | None) -> Any:  # noqa: ANN401 - a context manager
    return tenant_transaction(
        tenant_id=actor.tenant_id,
        actor_id=actor.user_id,
        actor_role=actor.actor_role,
        source_ip=source_ip,
    )


def _patient_found(
    session: Session, *, tenant_id: uuid.UUID, patient_id: uuid.UUID
) -> bool:
    """The patient is one of the caller's own live patients, read through the patients facade.

    Imported here rather than at module level: the patients facade embeds this module's
    `relationship_id` in its own reads, so a module-level import each way would be a cycle.
    """
    from app.modules.patients import service as patients_service

    return patient_id in patients_service.display_names(
        session, tenant_id=tenant_id, patient_ids=[patient_id]
    )


def _team(session: Session, *, actor: Actor, patient_id: uuid.UUID) -> CareTeamPublic:
    rows: Sequence[CareRelationship] = session.exec(
        select(CareRelationship)
        .where(
            col(CareRelationship.tenant_id) == actor.tenant_id,
            col(CareRelationship.patient_id) == patient_id,
            *_active(func.now()),
        )
        .order_by(col(CareRelationship.active_from), col(CareRelationship.id))
    ).all()
    staff = {
        member.user_id: member
        for member in users_roles.active_staff_holding(
            session, tenant_id=actor.tenant_id, role_codes=PRACTITIONER_ROLE_BY_CODE
        )
    }
    data: list[CareTeamMember] = []
    for row in rows:
        member = staff.get(row.practitioner_id)
        data.append(
            CareTeamMember(
                id=row.id,
                practitioner_id=row.practitioner_id,
                # A practitioner who has since been deactivated or lost every clinical role still
                # appears (the row is still active and must be visible to be ended), unnamed.
                practitioner_name=(
                    None if member is None else member.full_name or member.email
                ),
                active_from=row.active_from,
                source=row.source,
            )
        )
    return CareTeamPublic(data=data, count=len(data))


def list_care_team(
    *, actor: Actor, patient_id: uuid.UUID, source_ip: str | None = None
) -> CareTeamPublic | Refusal:
    """The patient's active relationships, oldest first. Audited as a `patient.read` of the team."""
    with _transaction(actor, source_ip) as session:
        if not _patient_found(
            session, tenant_id=actor.tenant_id, patient_id=patient_id
        ):
            audit.record(
                session,
                audit.AuditEvent(
                    action=PATIENT_READ,
                    result="DENIED",
                    resource_id=patient_id,
                    reason=PATIENT_NOT_FOUND,
                    source_ip=source_ip,
                ),
            )
            return Refusal(404, PATIENT_NOT_FOUND, "Patient not found")
        team = _team(session, actor=actor, patient_id=patient_id)
        audit.record(
            session,
            audit.AuditEvent(
                action=PATIENT_READ,
                result="SUCCESS",
                resource_id=patient_id,
                source_ip=source_ip,
                payload={
                    "purpose": PRACTICE_ADMINISTRATION,
                    "query_filters": ["care_team"],
                    "result_count": team.count,
                },
            ),
        )
        return team


def record_relationship(
    *,
    actor: Actor,
    patient_id: uuid.UUID,
    practitioner_id: uuid.UUID,
    source_ip: str | None = None,
) -> CareTeamPublic | Refusal:
    """Record an active relationship between a practitioner and a patient, audited (INV-4).

    Refused `404` for a patient that is not the caller's own, `422 PRACTITIONER_NOT_FOUND` for an
    account that is not an active practitioner of this organisation, and `409 ALREADY_IN_CARE_TEAM`
    when an active relationship already exists. Every refusal is audited `DENIED`.
    """
    with _transaction(actor, source_ip) as session:

        def refuse(status_code: int, code: str, message: str) -> Refusal:
            audit.record(
                session,
                audit.AuditEvent(
                    action=CARE_RELATIONSHIP_CREATE,
                    result="DENIED",
                    resource_id=patient_id,
                    reason=code,
                    source_ip=source_ip,
                    payload={"target_user_id": str(practitioner_id)},
                ),
            )
            return Refusal(status_code, code, message)

        if not _patient_found(
            session, tenant_id=actor.tenant_id, patient_id=patient_id
        ):
            return refuse(404, PATIENT_NOT_FOUND, "Patient not found")
        practitioners = {
            member.user_id
            for member in users_roles.active_staff_holding(
                session, tenant_id=actor.tenant_id, role_codes=PRACTITIONER_ROLE_BY_CODE
            )
        }
        if practitioner_id not in practitioners:
            return refuse(
                422,
                PRACTITIONER_NOT_FOUND,
                "Choose an active doctor or nurse in your practice",
            )
        # The database clock comes back with the check: it is the clock the rule reads (`now()` in
        # `relationship_id`), so an application clock running ahead cannot leave a just-recorded
        # relationship inactive until it catches up.
        existing, now = session.exec(
            select(
                relationship_id(
                    tenant_id=actor.tenant_id,
                    practitioner_id=practitioner_id,
                    patient_id=patient_id,
                ),
                func.now(),
            )
        ).one()
        if existing is not None:
            return refuse(
                409,
                ALREADY_IN_CARE_TEAM,
                "This practitioner is already in the patient's care team",
            )
        row = CareRelationship(
            tenant_id=actor.tenant_id,
            practitioner_id=practitioner_id,
            patient_id=patient_id,
            source=STAFF_RECORDED,
            active_from=now,
        )
        session.add(row)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=CARE_RELATIONSHIP_CREATE,
                result="SUCCESS",
                resource_id=patient_id,
                source_ip=source_ip,
                payload={
                    "care_relationship_id": str(row.id),
                    "target_user_id": str(practitioner_id),
                    "source": STAFF_RECORDED,
                },
            ),
        )
        return _team(session, actor=actor, patient_id=patient_id)


def end_relationship(
    *,
    actor: Actor,
    patient_id: uuid.UUID,
    care_relationship_id: uuid.UUID,
    source_ip: str | None = None,
) -> CareTeamPublic | Refusal:
    """End an active relationship now (`active_to = now()`), audited. The row is never deleted."""
    with _transaction(actor, source_ip) as session:
        found = session.exec(
            select(CareRelationship, func.now())
            .where(
                col(CareRelationship.id) == care_relationship_id,
                col(CareRelationship.tenant_id) == actor.tenant_id,
                col(CareRelationship.patient_id) == patient_id,
                *_active(func.now()),
            )
            .with_for_update(of=CareRelationship)
        ).first()
        if found is None:
            audit.record(
                session,
                audit.AuditEvent(
                    action=CARE_RELATIONSHIP_END,
                    result="DENIED",
                    resource_id=patient_id,
                    reason=RELATIONSHIP_NOT_FOUND,
                    source_ip=source_ip,
                    payload={"care_relationship_id": str(care_relationship_id)},
                ),
            )
            return Refusal(
                404, RELATIONSHIP_NOT_FOUND, "No active care relationship to end"
            )
        # The database clock, as on a create.
        row, now = found
        row.active_to = now
        session.add(row)
        session.flush()
        audit.record(
            session,
            audit.AuditEvent(
                action=CARE_RELATIONSHIP_END,
                result="SUCCESS",
                resource_id=patient_id,
                source_ip=source_ip,
                payload={
                    "care_relationship_id": str(row.id),
                    "target_user_id": str(row.practitioner_id),
                },
            ),
        )
        return _team(session, actor=actor, patient_id=patient_id)


def record_denial(
    *,
    actor: Actor,
    action: str,
    patient_id: uuid.UUID,
    reason: str,
    source_ip: str | None = None,
) -> None:
    """Audit a policy refusal of an upkeep route on its own transaction (nothing else to share)."""
    with _transaction(actor, source_ip) as session:
        audit.record(
            session,
            audit.AuditEvent(
                action=action,
                result="DENIED",
                resource_id=patient_id,
                reason=reason,
                source_ip=source_ip,
            ),
        )
