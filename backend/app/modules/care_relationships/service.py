"""Care relationships service facade — the treating-relationship rule's data source.

Design: the rule is `hasActiveCareRelationship(actor, patient_id)` in the central policy layer
(`docs/features/06-clinical-records/03-design.md`, "Treating-relationship check";
`docs/features/05-patients/03-design.md`, "Treating-relationship rule"), which reads
`care_relationships(tenant_id, practitioner_id, patient_id, clinic_id, active_from, active_to, source)`
under the same row-level security policy as the request. It is **never** inferred from clinic
membership and **never** widened to the tenant (`docs/features/03-users-and-roles/04-threat-model.md`
T-03.1; `05-patients/04-threat-model.md` T-05.9).

How the rule is wired, and where the boundary of this slice is:

- `active_relationship` / `has_active_relationship` answer the design's question from the table.
- `patient_resource` turns that answer into the `PatientResourceRef` the policy layer consumes, so a
  caller makes one call and then one `authorize(...)`:

      resource = care_relationships_service.patient_resource(actor=actor, patient_id=patient_id)
      authorize(actor, PATIENT_PERMISSIONS["read"], resource)

  `can()` then refuses with `403 AUTHZ_CARE_RELATIONSHIP_DENIED` when `patient_resource` found nothing.
- **The call sites are not in this slice.** The routes that must apply the rule are the patients and
  clinical-record routes, whose modules belong to other feature owners; adding the call there is a
  two-line change per route, and it is reported as the remaining gap rather than half-applied by
  reaching into another module. Until it lands, the rule can only *remove* access — an unwired rule
  denies nothing, and `can()`'s own checks are unchanged, so there is no fail-open.

## The interval

`active_from <= now AND (active_to IS NULL OR active_to > now)` — half-open `[active_from, active_to)`,
the boundary D-006 fixes as the interim fail-safe. An ended relationship (`active_to <= now`) and a
future-dated one (`active_from > now`) are both **inactive**, so a stale row cannot keep authorising a
read. If more than one interval is active for the same practitioner and patient — the design gives no
uniqueness rule for the pair — the most recent `active_from` wins, deterministically.

Everything runs inside `app.core.db.tenant_transaction(...)`: the forced policy scopes the read to the
request's tenant, and the explicit `tenant_id`/`practitioner_id` predicates are the second line of
defence for the connection role that currently bypasses the policy (see the migration docstring).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_
from sqlmodel import col, select

from app.core.db import tenant_transaction
from app.modules.care_relationships.models import CareRelationship
from app.modules.care_relationships.schemas import CareRelationshipRead
from app.modules.users_roles.policy import PatientResourceRef
from app.modules.users_roles.service import Actor

__all__ = [
    "active_relationship",
    "has_active_relationship",
    "patient_resource",
]


def active_relationship(
    *, actor: Actor, patient_id: uuid.UUID
) -> CareRelationshipRead | None:
    """The actor's active treating relationship with this patient, or `None`.

    `None` means "no active relationship", and it is the same answer whether the patient does not
    exist, belongs to another tenant, or simply has no relationship with this practitioner — none of
    which this function can distinguish, which is what keeps it from leaking existence.
    """
    now = datetime.now(UTC)
    with tenant_transaction(
        tenant_id=actor.tenant_id, actor_id=actor.user_id
    ) as session:
        statement = (
            select(CareRelationship)
            .where(
                # Every column goes through `col()`: SQLModel types a class attribute as its
                # *declared* type, so `CareRelationship.active_to > now` reads to a type checker as
                # `datetime | None > datetime`. `col()` recovers the SQL expression.
                col(CareRelationship.tenant_id) == actor.tenant_id,
                col(CareRelationship.practitioner_id) == actor.user_id,
                col(CareRelationship.patient_id) == patient_id,
                col(CareRelationship.active_from) <= now,
                or_(
                    col(CareRelationship.active_to).is_(None),
                    col(CareRelationship.active_to) > now,
                ),
            )
            .order_by(
                col(CareRelationship.active_from).desc(), col(CareRelationship.id)
            )
            .limit(1)
        )
        relationship = session.exec(statement).first()
        if relationship is None:
            return None
        return CareRelationshipRead.model_validate(relationship)


def has_active_relationship(*, actor: Actor, patient_id: uuid.UUID) -> bool:
    """The design's `hasActiveCareRelationship(actor, patient_id)`, as a boolean.

    The boolean form is for callers that need a filter rather than a decision — a list route narrowing
    its results, for instance. A caller about to authorise should use `patient_resource`, which carries
    the relationship id into the decision and into the audit event.
    """
    return active_relationship(actor=actor, patient_id=patient_id) is not None


def patient_resource(*, actor: Actor, patient_id: uuid.UUID) -> PatientResourceRef:
    """The policy-layer resource for a patient, with the relationship already resolved.

    One call, one read, and a resource that is safe to pass to `can()`: when no active relationship
    exists the ref carries `care_relationship_id = None` and the policy layer refuses with
    `403 AUTHZ_CARE_RELATIONSHIP_DENIED` — after the cross-tenant (`404`) and permission (`403`) checks,
    which is the design's decision order.
    """
    relationship = active_relationship(actor=actor, patient_id=patient_id)
    return PatientResourceRef(
        tenant_id=actor.tenant_id,
        patient_id=patient_id,
        care_relationship_id=None if relationship is None else relationship.id,
    )
