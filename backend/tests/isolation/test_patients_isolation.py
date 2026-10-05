"""Tenant isolation for `patients` — the first table it can be proved on.

Requirements: `docs/features/05-patients/01-requirements.md` R5, R6, R11. Scenarios S5, S6, S7, S15 in
`06-test-plan.md`.

These tests run as **`clinos_app`**, the least-privilege role the migration creates, via `SET LOCAL ROLE`
on the existing connection. That detail is the whole test: the deployment's normal connection is the
table owner and has `BYPASSRLS`, and **`BYPASSRLS` ignores every policy regardless of
`FORCE ROW LEVEL SECURITY`**. Proving isolation as the owner would prove nothing — it would pass with the
policy deleted. `SET LOCAL ROLE` is transaction-scoped, so a pooled connection cannot leak it.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine

# `SET LOCAL` so the role cannot outlive the transaction on a pooled connection.
AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
AS_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

_TENANT = text(
    "INSERT INTO tenants (id, slug, legal_name, status, data_region, retention_profile,"
    " created_at, updated_at) VALUES (:id, :slug, :slug, 'ACTIVE', 'ap-southeast-2', 'default',"
    " now(), now())"
)
_PATIENT = text(
    "INSERT INTO patients (tenant_id, given_name, family_name, date_of_birth, created_at,"
    " updated_at) VALUES (:tenant_id, :given_name, :family_name, '1990-01-01', now(), now())"
)


@pytest.fixture
def two_tenants() -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """One patient each, seeded as the owner — which bypasses RLS, so the seed is not the test."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        for tenant_id, name in ((a, "Ann"), (b, "Bob")):
            conn.execute(
                _TENANT, {"id": tenant_id, "slug": f"iso-{tenant_id.hex[:12]}"}
            )
            conn.execute(
                _PATIENT,
                {
                    "tenant_id": tenant_id,
                    "given_name": name,
                    "family_name": "Isolation",
                },
            )
    yield a, b
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM patients WHERE tenant_id IN (:a, :b)"), {"a": a, "b": b}
        )
        conn.execute(text("DELETE FROM tenants WHERE id IN (:a, :b)"), {"a": a, "b": b})


def _names(conn: object) -> list[str]:
    result = conn.execute(  # type: ignore[attr-defined]
        text("SELECT given_name FROM patients ORDER BY given_name")
    )
    return [row[0] for row in result]


@pytest.mark.usefixtures("two_tenants")
def test_no_tenant_setting_returns_zero_rows() -> None:
    """S6: a missing tenant context must fail closed, not return everything."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        assert _names(conn) == []


def test_rls_holds_without_an_application_filter(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """S5: the policy alone must scope the query — no `WHERE tenant_id` in this statement."""
    a, _ = two_tenants
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(a)})
        assert _names(conn) == ["Ann"]


def test_a_tenant_cannot_see_another_tenants_patient(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    _, b = two_tenants
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(b)})
        assert _names(conn) == ["Bob"]


def test_with_check_blocks_a_cross_tenant_insert(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """S7: a forged `tenant_id` is rejected by the write policy, not merely hidden afterwards."""
    a, b = two_tenants
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        engine.connect() as conn,
    ):
        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(b)})
            conn.execute(
                _PATIENT,
                {"tenant_id": a, "given_name": "Mallory", "family_name": "Forged"},
            )


def test_the_app_role_cannot_delete_a_patient(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """R11 / S15: never hard-deleted, enforced by the absence of a grant."""
    a, _ = two_tenants
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(a)})
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(text("DELETE FROM patients WHERE tenant_id = :a"), {"a": a})


def test_the_app_role_cannot_bypass_row_level_security() -> None:
    """The finding that made this migration include a role at all.

    `FORCE ROW LEVEL SECURITY` defeats the *owner* exemption and nothing else. A role holding
    `BYPASSRLS` — which the deployment's connection role does — reads every row with the policy in
    place, so the policy is decoration until the application stops connecting as it.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'clinos_app'"
            )
        ).one()
    assert row.rolsuper is False
    assert row.rolbypassrls is False
