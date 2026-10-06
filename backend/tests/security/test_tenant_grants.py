"""S9/S10 — the privileges `clinos_app` actually holds on the tenancy tables.

`docs/features/01-tenancy-and-clinics/06-test-plan.md` S9 (*"app role cannot write `tenants`; cannot read
`retention_profile`"*) and S10 (*"`DELETE`/`TRUNCATE` raise `42501 insufficient_privilege`"*). The
evidence is the catalogue and the executed refusals, not the migration source:
`information_schema.role_table_grants` and `information_schema.column_privileges` answer what the role
may do, and each refusal is attempted rather than described.

## One deviation is pinned here rather than asserted away

`03-design.md` "Database privileges" says `REVOKE ALL ON tenants FROM clinos_app`, with column-level
`SELECT` as the whole protection. `clinos_app` **does** hold table-level `INSERT` on `tenants`:
`f96bc0861b16` grants it deliberately, because self-service organisation signup inserts the tenant and
the design's `REVOKE ALL` assumes central provisioning (that migration's deviation 4 — *"Approved
deviation, recorded against that decision"*). This file asserts the state that exists and names where the
deviation is recorded, so narrowing it later fails here and forces the change to be deliberate. The
refusals that matter — `UPDATE`, `DELETE`, and both withheld columns — are asserted as refusals.

Every attempt that must fail gets its own transaction: a failed statement aborts the transaction it ran
in, so a second statement in the same block would raise `InFailedSqlTransaction` and prove nothing.

The blanket rules — `clinos_app` owns nothing, holds no `BYPASSRLS` and no `DELETE`/`TRUNCATE` on any
tenant table — are asserted in `tests/isolation/test_app_role_is_not_owner.py`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ProgrammingError

from app.core.db import engine

# `SET LOCAL` so the role cannot outlive the transaction on a pooled connection.
AS_APP_ROLE = text("SET LOCAL ROLE clinos_app")

_TABLE_GRANTS = text(
    "SELECT privilege_type FROM information_schema.role_table_grants"
    " WHERE grantee = 'clinos_app' AND table_name = :table"
)
# Column-level `SELECT` only: `information_schema.column_privileges` also expands a table-level
# privilege (here `INSERT`) across every column, which would otherwise look like a column grant.
_SELECT_COLUMN_GRANTS = text(
    "SELECT column_name FROM information_schema.column_privileges"
    " WHERE grantee = 'clinos_app' AND table_name = :table"
    " AND privilege_type = 'SELECT'"
)
_TABLE_OWNER = text(
    "SELECT r.rolname FROM pg_class c"
    " JOIN pg_namespace n ON n.oid = c.relnamespace"
    " JOIN pg_roles r ON r.oid = c.relowner"
    " WHERE n.nspname = 'public' AND c.relname = :table"
)

# The design's grants (`01-tenancy-and-clinics/03-design.md`, "Database privileges";
# `care_relationships` has no design grant section and follows the class rule in `04-database-erd.md`
# §6: `SELECT, INSERT, UPDATE`, never `DELETE` where retention may apply).
TENANT_TABLE_GRANTS = {
    "clinics": {"SELECT", "INSERT", "UPDATE"},
    "care_relationships": {"SELECT", "INSERT", "UPDATE"},
}

# `tenants` is global, so column-level grants are its protection: `retention_profile` and
# `legal_name` are withheld from the application role.
TENANTS_SELECT_COLUMNS = {"id", "slug", "status", "data_region"}

# The one table-level write grant on `tenants`, and the migration that records it as an approved
# deviation (`f96bc0861b16`, deviation 4).
TENANTS_TABLE_GRANTS = {"INSERT"}


@contextmanager
def _as_app_role() -> Iterator[Connection]:
    """One transaction as `clinos_app`, with no tenant context set."""
    with engine.connect() as conn, conn.begin():
        conn.execute(AS_APP_ROLE)
        yield conn


def _refused(statement: str) -> None:
    """Assert that `clinos_app` is refused this statement, in a transaction of its own."""
    with pytest.raises(ProgrammingError, match="permission denied"):
        with _as_app_role() as conn:
            conn.execute(text(statement))


def test_the_app_role_holds_exactly_the_declared_grants() -> None:
    with engine.connect() as conn:
        for table, expected in TENANT_TABLE_GRANTS.items():
            granted = {row[0] for row in conn.execute(_TABLE_GRANTS, {"table": table})}
            assert granted == expected, (
                f"{table} grants for clinos_app: {sorted(granted)}"
            )


def test_tenants_grants_are_column_level_read_plus_the_recorded_insert() -> None:
    """S9, with the deviation named: read is column-level, and `INSERT` is the one table-level grant."""
    with engine.connect() as conn:
        table_grants = {
            row[0] for row in conn.execute(_TABLE_GRANTS, {"table": "tenants"})
        }
        columns = {
            row[0] for row in conn.execute(_SELECT_COLUMN_GRANTS, {"table": "tenants"})
        }

    assert table_grants == TENANTS_TABLE_GRANTS, (
        "the table-level grants on `tenants` changed. `INSERT` is the deviation recorded in "
        "`f96bc0861b16` (signup creates the tenant); any other table-level grant — `SELECT` above all — "
        f"would expose `retention_profile`. Found {sorted(table_grants)}"
    )
    assert columns == TENANTS_SELECT_COLUMNS


def test_the_app_role_cannot_read_a_withheld_tenant_column() -> None:
    with _as_app_role() as conn:
        # The granted columns are readable...
        conn.execute(
            text("SELECT id, slug, status, data_region FROM tenants LIMIT 1")
        ).all()

    # ...and the withheld ones are not. `retention_profile` is CONFIDENTIAL; `legal_name` is not in the
    # grant either. Each refusal runs in its own transaction (see the module docstring).
    _refused("SELECT retention_profile FROM tenants LIMIT 1")
    _refused("SELECT legal_name FROM tenants LIMIT 1")


def test_the_insert_deviation_is_real_and_leaves_no_row() -> None:
    """The deviation asserted by execution, inside a transaction that is rolled back.

    `clinos_app` can create a tenant because signup needs it (`f96bc0861b16`, deviation 4). Pinning it
    here means a later narrowing of the grant is a deliberate change with a failing test rather than a
    silent one. The row never survives: `clinos_app` holds no `DELETE` on `tenants`, so the rollback is
    the cleanup.
    """
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(AS_APP_ROLE)
            conn.execute(
                text(
                    "INSERT INTO tenants (slug, legal_name, status, data_region, retention_profile,"
                    " created_at, updated_at)"
                    " VALUES ('grant-probe', 'Grant Probe', 'ACTIVE', 'ap-southeast-2', 'default',"
                    " now(), now())"
                )
            )
            # `slug` is one of the four granted columns, so the inserted row can be read back.
            assert (
                conn.execute(
                    text("SELECT slug FROM tenants WHERE slug = 'grant-probe'")
                ).scalar_one()
                == "grant-probe"
            )
        finally:
            transaction.rollback()


def test_the_app_role_cannot_update_or_delete_tenants() -> None:
    """No `UPDATE` and no `DELETE`; `INSERT` is the single recorded deviation."""
    _refused("UPDATE tenants SET status = 'SUSPENDED'")
    _refused("DELETE FROM tenants")


def test_the_app_role_cannot_delete_or_truncate_clinics() -> None:
    """S10, on the table itself: neither grant exists, so the refusal is `42501`."""
    _refused("DELETE FROM clinics")
    _refused("TRUNCATE TABLE clinics")


def test_the_migrator_owns_clinics_and_the_app_role_owns_neither_table() -> None:
    """`03-design.md`: `ALTER TABLE clinics OWNER TO clinos_migrator` — `clinos_app` never owns a table."""
    with engine.connect() as conn:
        assert (
            conn.execute(_TABLE_OWNER, {"table": "clinics"}).scalar_one()
            == "clinos_migrator"
        )
        assert (
            conn.execute(_TABLE_OWNER, {"table": "care_relationships"}).scalar_one()
            != "clinos_app"
        )
