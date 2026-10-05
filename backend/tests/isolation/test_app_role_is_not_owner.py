"""T1-11 — the application role owns nothing, bypasses nothing, and cannot delete a tenant row.

`FORCE ROW LEVEL SECURITY` closes the owner exemption and nothing else. A role holding `BYPASSRLS`
reads every row with every policy in place, and an owner can drop the policy that constrains it, so
`clinos_app` must be neither. These assertions read `pg_roles`, `pg_class` and
`information_schema.role_table_grants` after the migrations — the grant listing, not the migration
source, is the evidence.

The roles are created `NOLOGIN PASSWORD NULL` on purpose: a credential does not belong in a
migration and cannot be rotated from one, so the deployment sets it out of band. That is why
`rolcanlogin` is asserted false here rather than a password being checked.
"""

from sqlalchemy import text

from app.core.db import engine

ROLES = (
    "clinos_app",
    "clinos_migrator",
    "clinos_retention",
    "clinos_readonly_audit",
    "clinos_auth",
)

_ROLE_ATTRIBUTES = text(
    "SELECT rolsuper, rolbypassrls, rolcanlogin, rolcreaterole, rolcreatedb "
    "FROM pg_roles WHERE rolname = :role"
)
_TABLES_OWNED_BY_APP = text(
    "SELECT c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "JOIN pg_roles r ON r.oid = c.relowner "
    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND r.rolname = 'clinos_app'"
)
_APP_DELETE_OR_TRUNCATE_ON_TENANT_TABLES = text(
    "SELECT g.table_name, g.privilege_type "
    "FROM information_schema.role_table_grants g "
    "WHERE g.grantee = 'clinos_app' AND g.privilege_type IN ('DELETE', 'TRUNCATE') "
    "AND EXISTS ("
    "  SELECT 1 FROM information_schema.columns c "
    "  WHERE c.table_schema = g.table_schema AND c.table_name = g.table_name "
    "    AND c.column_name = 'tenant_id'"
    ")"
)


def test_the_five_roles_exist_with_least_privilege_attributes() -> None:
    with engine.connect() as conn:
        actual = {
            row[0]
            for row in conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'clinos%'")
            )
        }
        assert actual == set(ROLES), (
            f"the design names exactly {sorted(ROLES)}; the cluster has {sorted(actual)}"
        )

        for role in ROLES:
            row = conn.execute(_ROLE_ATTRIBUTES, {"role": role}).one()
            rolsuper, rolbypassrls, rolcanlogin, rolcreaterole, rolcreatedb = row
            assert rolsuper is False, f"{role} is SUPERUSER"
            assert rolbypassrls is False, (
                f"{role} holds BYPASSRLS — that role reads every tenant's rows with every policy "
                "in place, so the policy is decoration"
            )
            assert rolcanlogin is False, (
                f"{role} can LOGIN — a credential belongs out of band, not in a migration"
            )
            assert rolcreaterole is False, f"{role} can create roles"
            assert rolcreatedb is False, f"{role} can create databases"


def test_the_app_role_owns_no_table() -> None:
    with engine.connect() as conn:
        owned = [row[0] for row in conn.execute(_TABLES_OWNED_BY_APP)]
    assert owned == [], (
        "`clinos_app` owns "
        + ", ".join(owned)
        + " — an owner can drop the policy that "
        "constrains it, and FORCE only removes the owner's exemption, it does not make ownership "
        "safe"
    )


def test_the_app_role_holds_no_delete_or_truncate_on_a_tenant_table() -> None:
    """R11 / the no-hard-delete rule: enforced by the absence of a grant, not by convention."""
    with engine.connect() as conn:
        rows = conn.execute(_APP_DELETE_OR_TRUNCATE_ON_TENANT_TABLES).all()
    assert rows == [], (
        "`clinos_app` holds DELETE or TRUNCATE on a tenant table: "
        + ", ".join(f"{table}.{privilege}" for table, privilege in rows)
    )
