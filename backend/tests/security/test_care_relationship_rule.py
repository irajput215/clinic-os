"""R7 — the treating-relationship rule, and the policy decision that consumes it.

The consumers name the rule and its refusal verbatim: a read outside the relationship is
`403 AUTHZ_CARE_RELATIONSHIP_DENIED` (`docs/features/05-patients/01-requirements.md` R7 and its negative
decision matrix; `docs/features/06-clinical-records/01-requirements.md` R11; `06-clinical-records/
05-data-and-audit.md`, denial reason), it is **never** inferred from clinic membership and **never**
widened to the tenant (`03-users-and-roles/04-threat-model.md` T-03.1).

The design puts the rule in the central policy layer as step 4 of the decision order
(`03-users-and-roles/03-design.md`, "The central policy layer"). This test exercises exactly that seam:

    resource = care_relationships.service.patient_resource(actor=..., patient_id=...)
    authorize(actor, "patient:read", resource)

`can()` stays pure — the verdict arrives as data — so the order of the refusals is asserted here rather
than left to whichever route calls it first. `tests/isolation/test_care_relationships_isolation.py`
covers the data half (RLS, the interval, the tenant predicate).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.db import engine
from app.modules.care_relationships import service
from app.modules.users_roles.policy import (
    Actor,
    DecisionCode,
    PatientResourceRef,
    can,
    enforce,
)
from tests.utils.seeding import (
    create_patient,
    create_practitioner,
    create_relationship,
    create_tenant,
    delete_tenancy_rows,
)

PATIENT_READ = "patient:read"

# The code the consumers name, asserted as a literal so a rename in `DecisionCode` cannot pass quietly.
DOCUMENTED_CODE = "AUTHZ_CARE_RELATIONSHIP_DENIED"


class Seeded:
    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        practitioner_id: uuid.UUID,
        related_patient_id: uuid.UUID,
        ended_patient_id: uuid.UUID,
        stranger_patient_id: uuid.UUID,
    ) -> None:
        self.tenant_id = tenant_id
        self.practitioner_id = practitioner_id
        self.related_patient_id = related_patient_id
        self.ended_patient_id = ended_patient_id
        self.stranger_patient_id = stranger_patient_id

    def actor(
        self, *, permissions: frozenset[str] = frozenset({PATIENT_READ})
    ) -> Actor:
        return Actor(
            user_id=self.practitioner_id,
            tenant_id=self.tenant_id,
            is_active=True,
            permissions=permissions,
        )


@pytest.fixture
def seeded() -> Iterator[dict[str, Seeded]]:
    """Two tenants, each with a practitioner and three patients: related, ended, and a stranger."""
    with engine.begin() as conn:
        seeded: dict[str, Seeded] = {}
        for label in ("a", "b"):
            tenant_id = create_tenant(conn, name=f"Relationship Rule {label.upper()}")
            practitioner_id = create_practitioner(conn, tenant_id=tenant_id)
            row = Seeded(
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                related_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Related {label.upper()}"
                ),
                ended_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Ended {label.upper()}"
                ),
                stranger_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Stranger {label.upper()}"
                ),
            )
            now = datetime.now(UTC)
            create_relationship(
                conn,
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                patient_id=row.related_patient_id,
                active_from=now - timedelta(hours=1),
            )
            create_relationship(
                conn,
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                patient_id=row.ended_patient_id,
                active_from=now - timedelta(days=10),
                active_to=now - timedelta(days=1),
            )
            seeded[label] = row
    yield seeded
    with engine.begin() as conn:
        delete_tenancy_rows(conn, *(row.tenant_id for row in seeded.values()))


def test_an_active_relationship_allows_the_read(seeded: dict[str, Seeded]) -> None:
    a = seeded["a"]
    resource = service.patient_resource(
        actor=a.actor(), patient_id=a.related_patient_id
    )

    decision = can(a.actor(), PATIENT_READ, resource)

    assert decision.allowed is True
    assert decision.code is DecisionCode.ALLOWED
    assert resource.care_relationship_id is not None


def test_no_relationship_is_refused_with_the_documented_code(
    seeded: dict[str, Seeded],
) -> None:
    a = seeded["a"]
    resource = service.patient_resource(
        actor=a.actor(), patient_id=a.stranger_patient_id
    )

    decision = can(a.actor(), PATIENT_READ, resource)

    assert decision.allowed is False
    assert decision.status_code == 403
    assert decision.code is DecisionCode.CARE_RELATIONSHIP_DENIED
    assert decision.code.value == DOCUMENTED_CODE


def test_the_refusal_raises_the_machine_readable_code(
    seeded: dict[str, Seeded],
) -> None:
    """What a route gets: one `403` with a stable code and no patient data in the message."""
    a = seeded["a"]
    resource = service.patient_resource(
        actor=a.actor(), patient_id=a.stranger_patient_id
    )

    with pytest.raises(HTTPException) as raised:
        enforce(can(a.actor(), PATIENT_READ, resource))

    assert raised.value.status_code == 403
    detail = raised.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == DOCUMENTED_CODE
    assert "Stranger A" not in str(detail)


def test_an_ended_relationship_is_refused(seeded: dict[str, Seeded]) -> None:
    a = seeded["a"]
    resource = service.patient_resource(actor=a.actor(), patient_id=a.ended_patient_id)

    decision = can(a.actor(), PATIENT_READ, resource)

    assert decision.status_code == 403
    assert decision.code is DecisionCode.CARE_RELATIONSHIP_DENIED


def test_the_tenant_check_precedes_the_relationship_rule(
    seeded: dict[str, Seeded],
) -> None:
    """R6: across a tenant boundary the answer is `404`, never the relationship `403`.

    A `403` would confirm the patient exists in the other tenant; the design fixes the order, so the
    tenant mismatch is decided before any resource rule is examined.
    """
    a, b = seeded["a"], seeded["b"]
    resource = PatientResourceRef(
        tenant_id=b.tenant_id,
        patient_id=b.related_patient_id,
        care_relationship_id=None,
    )

    decision = can(a.actor(), PATIENT_READ, resource)

    assert decision.status_code == 404
    assert decision.code is DecisionCode.CROSS_TENANT


def test_the_permission_check_precedes_the_relationship_rule(
    seeded: dict[str, Seeded],
) -> None:
    """A caller without the permission hears about the permission, not about the relationship."""
    a = seeded["a"]
    actor = a.actor(permissions=frozenset())
    resource = service.patient_resource(actor=actor, patient_id=a.related_patient_id)

    decision = can(actor, PATIENT_READ, resource)

    assert decision.status_code == 403
    assert decision.code is DecisionCode.PERMISSION_NOT_HELD


def test_another_tenants_relationship_never_satisfies_the_rule(
    seeded: dict[str, Seeded],
) -> None:
    """The rule is not widened to the tenant: B's practitioner cannot borrow A's relationship."""
    a, b = seeded["a"], seeded["b"]
    resource = service.patient_resource(
        actor=b.actor(), patient_id=a.related_patient_id
    )

    assert resource.care_relationship_id is None
    decision = can(b.actor(), PATIENT_READ, resource)
    assert decision.code is DecisionCode.CARE_RELATIONSHIP_DENIED


def test_the_resource_cannot_skip_the_verdict() -> None:
    """`care_relationship_id` has no default, so forgetting to resolve it is a `TypeError`.

    A default of `None` would fail closed only by luck; a default of "active" would fail open. Neither
    exists: the resolver must state the verdict at the call site.
    """
    with pytest.raises(TypeError):
        PatientResourceRef(tenant_id=uuid.uuid4(), patient_id=uuid.uuid4())  # type: ignore[call-arg]
