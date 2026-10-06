"""Tenant isolation and the interval rules for `care_relationships`.

The table is the authorisation input Feature 05's R7 and Feature 06's R11 name: a practitioner may read
or write a patient's record only through an **active** treating relationship, resolved under the same
row-level security policy as the request (`docs/features/06-clinical-records/03-design.md`,
"Treating-relationship check"; `docs/features/03-users-and-roles/04-threat-model.md` T-03.1).

Two halves, for the two controls:

- **The database half** runs as `clinos_app` via `SET LOCAL ROLE`, the only way to prove the policy is
  what scopes a query: the process engine connects as the owner with `BYPASSRLS`, and `BYPASSRLS` ignores
  every policy regardless of `FORCE`.
- **The service half** runs through `app.modules.care_relationships.service`, which is what a route would
  call. It asserts the tenant predicate, the practitioner predicate and the interval rule together — the
  place a stale relationship would otherwise keep authorising a read.

`tests/security/test_care_relationship_rule.py` asserts the policy decision that consumes this data.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.db import engine
from app.modules.care_relationships import service
from app.modules.care_relationships.models import CareRelationship
from app.modules.care_relationships.schemas import CareRelationshipRead
from app.modules.users_roles.policy import Actor
from tests.utils.seeding import (
    create_clinic,
    create_patient,
    create_practitioner,
    create_relationship,
    create_tenant,
    delete_tenancy_rows,
)

AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
AS_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


class Seeded:
    """One tenant's rows, so a test can name exactly what it is asserting against."""

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        practitioner_id: uuid.UUID,
        active_patient_id: uuid.UUID,
        ended_patient_id: uuid.UUID,
        future_patient_id: uuid.UUID,
        stranger_patient_id: uuid.UUID,
    ) -> None:
        self.tenant_id = tenant_id
        self.practitioner_id = practitioner_id
        self.active_patient_id = active_patient_id
        self.ended_patient_id = ended_patient_id
        self.future_patient_id = future_patient_id
        self.stranger_patient_id = stranger_patient_id

    @property
    def actor(self) -> Actor:
        return Actor(
            user_id=self.practitioner_id,
            tenant_id=self.tenant_id,
            is_active=True,
            permissions=frozenset({"patient:read"}),
        )


@pytest.fixture
def two_tenants() -> Iterator[dict[str, Seeded]]:
    """Two tenants with a practitioner each, and four patients covering every interval case."""
    with engine.begin() as conn:
        seeded: dict[str, Seeded] = {}
        for label in ("a", "b"):
            tenant_id = create_tenant(
                conn, name=f"Relationship Isolation {label.upper()}"
            )
            practitioner_id = create_practitioner(conn, tenant_id=tenant_id)
            clinic_id = create_clinic(
                conn, tenant_id=tenant_id, name=f"Site {label.upper()}"
            )
            row = Seeded(
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                active_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Active {label.upper()}"
                ),
                ended_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Ended {label.upper()}"
                ),
                future_patient_id=create_patient(
                    conn, tenant_id=tenant_id, given_name=f"Future {label.upper()}"
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
                patient_id=row.active_patient_id,
                clinic_id=clinic_id,
                active_from=now - timedelta(days=1),
            )
            create_relationship(
                conn,
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                patient_id=row.ended_patient_id,
                clinic_id=clinic_id,
                active_from=now - timedelta(days=30),
                active_to=now - timedelta(days=1),
            )
            create_relationship(
                conn,
                tenant_id=tenant_id,
                practitioner_id=practitioner_id,
                patient_id=row.future_patient_id,
                clinic_id=clinic_id,
                active_from=now + timedelta(days=1),
            )
            seeded[label] = row
    yield seeded
    with engine.begin() as conn:
        delete_tenancy_rows(conn, *(row.tenant_id for row in seeded.values()))


def _patient_names(conn: object) -> list[str]:
    result = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT p.given_name FROM care_relationships cr JOIN patients p ON p.id = cr.patient_id"
        )
    )
    return sorted(row[0] for row in result)


def test_no_tenant_context_reads_zero_rows() -> None:
    """A missing context matches no row rather than every row (`NULLIF` guard)."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        assert (
            conn.execute(text("SELECT count(*) FROM care_relationships")).scalar_one()
            == 0
        )


def test_rls_holds_without_an_application_filter(
    two_tenants: dict[str, Seeded],
) -> None:
    """The policy alone scopes the query — there is no `WHERE tenant_id` in the statement below."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["a"].tenant_id)})
        assert _patient_names(conn) == ["Active A", "Ended A", "Future A"]


def test_with_check_blocks_a_cross_tenant_insert(
    two_tenants: dict[str, Seeded],
) -> None:
    """A forged `tenant_id` is refused by the write policy, not hidden after the fact."""
    a, b = two_tenants["a"], two_tenants["b"]
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        engine.connect() as conn,
    ):
        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(b.tenant_id)})
            conn.execute(
                text(
                    "INSERT INTO care_relationships (tenant_id, practitioner_id, patient_id,"
                    " active_from, source, created_at, updated_at)"
                    " VALUES (:tenant_id, :practitioner_id, :patient_id, now(), 'FORGED',"
                    " now(), now())"
                ),
                {
                    "tenant_id": a.tenant_id,
                    "practitioner_id": b.practitioner_id,
                    "patient_id": b.active_patient_id,
                },
            )


def test_the_app_role_cannot_delete_or_truncate_a_relationship(
    two_tenants: dict[str, Seeded],
) -> None:
    """No `DELETE`: ending a relationship is `active_to`, and authorisation evidence must not vanish.

    One transaction per refusal, because a failed statement aborts the transaction it ran in.
    """
    for statement in (
        "DELETE FROM care_relationships",
        "TRUNCATE TABLE care_relationships",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with engine.connect() as conn, conn.begin():
                conn.execute(AS_APP_ROLE)
                conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["a"].tenant_id)})
                conn.execute(text(statement))


def test_an_interval_may_not_end_before_it_starts(
    two_tenants: dict[str, Seeded],
) -> None:
    """The check constraint, by name: `ck_care_relationships_active_interval`."""
    a = two_tenants["a"]
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError, match="ck_care_relationships_active_interval"):
        with engine.begin() as conn:
            create_relationship(
                conn,
                tenant_id=a.tenant_id,
                practitioner_id=a.practitioner_id,
                patient_id=a.stranger_patient_id,
                active_from=now,
                active_to=now - timedelta(seconds=1),
            )


def test_the_service_finds_the_active_relationship(
    two_tenants: dict[str, Seeded],
) -> None:
    a = two_tenants["a"]
    relationship = service.active_relationship(
        actor=a.actor, patient_id=a.active_patient_id
    )
    assert relationship is not None
    assert isinstance(relationship, CareRelationshipRead)
    assert relationship.patient_id == a.active_patient_id
    assert relationship.practitioner_id == a.practitioner_id
    assert relationship.active_to is None
    assert service.has_active_relationship(
        actor=a.actor, patient_id=a.active_patient_id
    )


def test_an_ended_relationship_is_not_active(two_tenants: dict[str, Seeded]) -> None:
    """`active_to <= now` is expired: a stale row must not keep authorising a read."""
    a = two_tenants["a"]
    assert (
        service.active_relationship(actor=a.actor, patient_id=a.ended_patient_id)
        is None
    )
    assert not service.has_active_relationship(
        actor=a.actor, patient_id=a.ended_patient_id
    )


def test_a_future_dated_relationship_is_not_active(
    two_tenants: dict[str, Seeded],
) -> None:
    """The interval is half-open `[active_from, active_to)`, so `active_from > now` is not yet active."""
    a = two_tenants["a"]
    assert (
        service.active_relationship(actor=a.actor, patient_id=a.future_patient_id)
        is None
    )


def test_a_patient_with_no_relationship_has_none(
    two_tenants: dict[str, Seeded],
) -> None:
    a = two_tenants["a"]
    assert (
        service.active_relationship(actor=a.actor, patient_id=a.stranger_patient_id)
        is None
    )


def test_another_tenants_relationship_is_invisible(
    two_tenants: dict[str, Seeded],
) -> None:
    """Tenant B's practitioner has an active relationship with their own patient, not with A's.

    The row for A exists; the tenant predicate and the policy are what make the answer `None`, so a
    cross-tenant relationship can never be mistaken for one of the caller's own.
    """
    a, b = two_tenants["a"], two_tenants["b"]
    assert (
        service.active_relationship(actor=b.actor, patient_id=a.active_patient_id)
        is None
    )
    assert (
        service.active_relationship(actor=a.actor, patient_id=b.active_patient_id)
        is None
    )


def test_the_policy_resource_carries_the_relationship_id(
    two_tenants: dict[str, Seeded],
) -> None:
    """What the policy layer consumes, and what the audit envelope records as `care_relationship_id`."""
    a = two_tenants["a"]
    relationship = service.active_relationship(
        actor=a.actor, patient_id=a.active_patient_id
    )
    assert relationship is not None

    resource = service.patient_resource(actor=a.actor, patient_id=a.active_patient_id)
    assert resource.tenant_id == a.tenant_id
    assert resource.patient_id == a.active_patient_id
    assert resource.care_relationship_id == relationship.id

    absent = service.patient_resource(actor=a.actor, patient_id=a.stranger_patient_id)
    assert absent.care_relationship_id is None


def test_the_model_defaults_are_open_ended_and_timezone_aware() -> None:
    """`active_to is None` is the open-ended state; the interval check allows it and nothing else does.

    Nothing here reaches the database: the seed helpers insert through SQL, so this is what exercises
    the model's own defaults.
    """
    relationship = CareRelationship(
        tenant_id=uuid.uuid4(),
        practitioner_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        source="SYNTHETIC_TEST",
    )

    assert relationship.active_to is None
    assert relationship.clinic_id is None
    assert relationship.active_from.tzinfo is not None
    assert relationship.created_at.tzinfo is not None
