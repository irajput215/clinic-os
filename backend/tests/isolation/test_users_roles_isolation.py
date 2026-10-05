"""RLS isolation for the RBAC tables — `roles`, `role_permissions`, `user_roles`.

Requirement R11 and scenarios S10/S11: a missing tenant setting returns zero rows (the `NULLIF`
guard), a tenant sees only its own rows, a forged `tenant_id` write is refused by `WITH CHECK`, and
the application role cannot write global reference data or hard-delete a grant.

These run as **`clinos_app`** via `SET LOCAL ROLE` for the same reason as the `patients` isolation
suite: the deployment connection is the table owner with `BYPASSRLS`, and proving isolation on it
would pass with every policy deleted.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine
from app.modules.users_roles.service import provision_tenant_roles

AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")
AS_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

_TENANT = text(
    "INSERT INTO tenants (id, slug, legal_name, status, data_region, retention_profile,"
    " created_at, updated_at) VALUES (:id, :slug, :slug, 'ACTIVE', 'ap-southeast-2', 'default',"
    " now(), now())"
)


@pytest.fixture
def two_tenants() -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    """Two organisations, each with its seven seeded role bundles."""
    a, b = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        for tenant_id in (a, b):
            conn.execute(
                _TENANT, {"id": tenant_id, "slug": f"rls-{tenant_id.hex[:12]}"}
            )
    provision_tenant_roles(tenant_id=a)
    provision_tenant_roles(tenant_id=b)
    yield a, b
    with engine.begin() as conn:
        for tenant_id in (a, b):
            for statement in (
                "DELETE FROM user_roles WHERE tenant_id = :tenant_id",
                "DELETE FROM role_permissions WHERE tenant_id = :tenant_id",
                "DELETE FROM roles WHERE tenant_id = :tenant_id",
                "DELETE FROM tenants WHERE id = :tenant_id",
            ):
                conn.execute(text(statement), {"tenant_id": tenant_id})


def test_no_tenant_setting_returns_zero_rows() -> None:
    """S10: a missing tenant context matches nothing, never everything."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        for table in ("roles", "role_permissions", "user_roles"):
            assert (
                int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
                == 0
            ), f"{table} returned rows without an app.tenant_id"


def test_a_tenant_sees_only_its_own_role_bundle(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    a, b = two_tenants
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(a)})
        # Fourteen rows exist across the two tenants; the policy alone returns seven.
        assert int(conn.execute(text("SELECT count(*) FROM roles")).scalar_one()) == 7

    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        conn.execute(AS_TENANT, {"tenant_id": str(b)})
        assert int(conn.execute(text("SELECT count(*) FROM roles")).scalar_one()) == 7


def test_with_check_blocks_a_cross_tenant_role_insert(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """S11: a forged `tenant_id` is refused by the write policy, not merely hidden afterwards."""
    a, _ = two_tenants
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        engine.connect() as conn,
    ):
        with conn.begin():
            conn.execute(AS_APP_ROLE)
            conn.execute(AS_TENANT, {"tenant_id": str(a)})
            conn.execute(
                text(
                    "INSERT INTO roles (id, tenant_id, code, name, is_system,"
                    " created_at, updated_at)"
                    " VALUES (gen_random_uuid(), :forged, 'DOCTOR', 'Forged', false,"
                    " now(), now())"
                ),
                {"forged": uuid.uuid4()},
            )


def test_the_app_role_cannot_write_global_permission_reference_data() -> None:
    """R7/S13: `permissions` is `SELECT` only; a tenant cannot invent a permission."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(
                text(
                    "INSERT INTO permissions (id, code, description)"
                    " VALUES (gen_random_uuid(), 'patient:merge', 'invented')"
                )
            )


def test_the_app_role_cannot_hard_delete_a_grant(
    two_tenants: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Deviation 3 in the migration: `SELECT, INSERT` only on the grant tables, no hard delete.

    One statement per transaction: a refused statement aborts the transaction, so a second statement
    in the same block would fail for the wrong reason.
    """
    a, _ = two_tenants
    for table in ("role_permissions", "user_roles"):
        with (
            pytest.raises(ProgrammingError, match="permission denied"),
            engine.connect() as conn,
        ):
            with conn.begin():
                conn.execute(AS_APP_ROLE)
                conn.execute(AS_TENANT, {"tenant_id": str(a)})
                conn.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": a},
                )
