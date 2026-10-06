"""Tenant isolation for `clinics` — the tenant-scoped child of `tenants`.

Requirements: R3 (tenant-scoped), R4 (RLS), R5 (no bypass), R6 (no context reads nothing), R7 (`WITH
CHECK`), R9 (`404`, never `403`), R11 (create/rename is tenant-scoped), R14 (absence across channels) in
`docs/features/01-tenancy-and-clinics/01-requirements.md`. Scenarios F8, F9, S4, S5, S6, S7, S10 and S11
in `06-test-plan.md`.

The database half runs as **`clinos_app`** via `SET LOCAL ROLE`, exactly as
`tests/isolation/test_patients_isolation.py` does and for the same reason: the deployment's normal
connection is the table owner and holds `BYPASSRLS`, and `BYPASSRLS` ignores every policy regardless of
`FORCE ROW LEVEL SECURITY`, so proving isolation as the owner would prove nothing — it would pass with
the policy deleted. `SET LOCAL ROLE` is transaction-scoped, so a pooled connection cannot leak it.

The service half runs through `app.modules.clinics.service`, which is the path a route takes. It asserts
the application predicate rather than RLS: the process-wide engine still connects as the owner, so the
policy is not what scopes that query today. Both controls are asserted, and neither is removed on the day
the other starts working.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db import engine
from app.modules.clinics import service
from app.modules.clinics.models import Clinic
from tests.utils.seeding import create_clinic, create_tenant, delete_tenancy_rows

# `SET LOCAL` so the role cannot outlive the transaction on a pooled connection.
AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
AS_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")


@pytest.fixture
def two_tenants() -> Iterator[dict[str, uuid.UUID]]:
    """One clinic each for tenant A and tenant B, seeded as the owner (which bypasses RLS)."""
    with engine.begin() as conn:
        a = create_tenant(conn, name="Clinic Isolation A")
        b = create_tenant(conn, name="Clinic Isolation B")
        create_clinic(conn, tenant_id=a, name="Alpha Site")
        create_clinic(conn, tenant_id=b, name="Beta Site")
    yield {"a": a, "b": b}
    with engine.begin() as conn:
        delete_tenancy_rows(conn, a, b)


def _clinic_names(conn: object) -> list[str]:
    result = conn.execute(  # type: ignore[attr-defined]
        text("SELECT name FROM clinics ORDER BY name")
    )
    return [row[0] for row in result]


@pytest.mark.usefixtures("two_tenants")
def test_no_tenant_context_reads_zero_rows() -> None:
    """R6/S6: a missing tenant context fails closed, and it does not raise."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        assert _clinic_names(conn) == []


def test_the_nullif_guard_returns_zero_rows_where_the_naive_form_raises() -> None:
    """S4: the guard is what makes an *empty* setting harmless.

    `current_setting('app.tenant_id', true)` returns `NULL` when the setting is absent and `''` when it
    was set to an empty string. `NULLIF(..., '')` turns both into `NULL`, which matches no row; the
    naive `current_setting(...)::uuid` raises on the second, which is the defect this asserts rather
    than describes.
    """
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        guarded = conn.execute(
            text(
                "SELECT count(*) FROM clinics "
                "WHERE tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
            )
        ).scalar_one()
        assert guarded == 0

    # `DataError`, not `ProgrammingError`: the cast fails on the value, not on a privilege.
    with pytest.raises(DBAPIError, match="invalid input syntax for type uuid"):
        with engine.connect() as conn, conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(text("SELECT set_config('app.tenant_id', '', true)"))
            conn.execute(
                text(
                    "SELECT count(*) FROM clinics "
                    "WHERE tenant_id = current_setting('app.tenant_id', true)::uuid"
                )
            )


def test_rls_holds_without_an_application_filter(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """S5/T-TEN-3: the policy alone must scope the query — there is no `WHERE tenant_id` below."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["a"])})
        assert _clinic_names(conn) == ["Alpha Site"]


def test_a_tenant_cannot_see_another_tenants_clinic(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["b"])})
        assert _clinic_names(conn) == ["Beta Site"]


def test_with_check_blocks_a_cross_tenant_insert(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """R7/S7: a forged `tenant_id` is refused by the write policy, not merely hidden afterwards."""
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        engine.connect() as conn,
    ):
        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["b"])})
            conn.execute(
                text(
                    "INSERT INTO clinics (tenant_id, name, created_at, updated_at)"
                    " VALUES (:tenant_id, 'Forged Site', now(), now())"
                ),
                {"tenant_id": two_tenants["a"]},
            )


def test_the_app_role_cannot_delete_or_truncate_a_clinic(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """S10: no `DELETE` and no `TRUNCATE` — the design's "no DELETE where retention may apply".

    Each refusal gets its own transaction: a statement that fails aborts the transaction it ran in, so a
    second statement in the same block would raise `InFailedSqlTransaction` and prove nothing about the
    privilege.
    """
    for statement in ("DELETE FROM clinics", "TRUNCATE TABLE clinics"):
        with pytest.raises(ProgrammingError, match="permission denied"):
            with engine.connect() as conn, conn.begin():
                conn.execute(AS_APP_ROLE)
                conn.execute(AS_TENANT, {"tenant_id": str(two_tenants["a"])})
                conn.execute(text(statement))


def test_the_service_lists_only_the_callers_tenant(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """F8/R11: the tenant-scoped read path a route uses returns the caller's clinics and no others."""
    listing = service.list_clinics(tenant_id=two_tenants["a"], limit=25)
    assert [clinic.name for clinic in listing.data] == ["Alpha Site"]
    assert listing.count == 1

    other = service.list_clinics(tenant_id=two_tenants["b"], limit=25)
    assert [clinic.name for clinic in other.data] == ["Beta Site"]
    assert other.count == 1


def test_the_service_answers_none_for_another_tenants_clinic(
    two_tenants: dict[str, uuid.UUID],
) -> None:
    """R9/F9: another tenant's clinic is indistinguishable from an absent one, so a route answers `404`."""
    with engine.connect() as conn:
        clinic_id = uuid.UUID(
            str(
                conn.execute(
                    text("SELECT id FROM clinics WHERE tenant_id = :tenant_id"),
                    {"tenant_id": two_tenants["a"]},
                ).scalar_one()
            )
        )

    assert service.get_clinic(tenant_id=two_tenants["b"], clinic_id=clinic_id) is None
    own = service.get_clinic(tenant_id=two_tenants["a"], clinic_id=clinic_id)
    assert own is not None
    assert own.name == "Alpha Site"


def test_the_model_defaults_are_timezone_aware_and_set() -> None:
    """The columns the migration declares `NOT NULL` have a Python-side default as well.

    Nothing here reaches the database: the seed helpers insert through SQL, so without this the
    defaults would be exercised only by a service that cannot write yet.
    """
    clinic = Clinic(tenant_id=uuid.uuid4(), name="Default Site")

    assert isinstance(clinic.id, uuid.UUID)
    assert clinic.address is None
    assert clinic.phone is None
    assert clinic.created_at.tzinfo is not None
    assert clinic.updated_at.tzinfo is not None
