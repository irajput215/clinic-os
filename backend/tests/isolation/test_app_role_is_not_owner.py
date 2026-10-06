"""T1-11 — the application role owns nothing, bypasses nothing, and cannot hard-delete a tenant row.

`FORCE ROW LEVEL SECURITY` closes the owner exemption and nothing else. A role holding `BYPASSRLS`
reads every row with every policy in place, and an owner can drop the policy that constrains it, so
`clinos_app` must be neither. These assertions read `pg_roles`, `pg_class` and
`information_schema.role_table_grants` after the migrations — the grant listing, not the migration
source, is the evidence.

The roles are created `NOLOGIN PASSWORD NULL` on purpose: a credential does not belong in a
migration and cannot be rotated from one, so the deployment sets it out of band. That is why
`rolcanlogin` is asserted false here rather than a password being checked.

**The no-DELETE control is every tenant table, with exactly one documented carve-out.** Requirement
R14 — *"A user is deactivated, not hard-deleted; clinical attribution survives"*, whose acceptance is
*"No `DELETE` grant on `users`"* — is a tenant-data rule, and `03-users-and-roles/03-design.md`
§Database privileges revokes `DELETE` and `TRUNCATE` on `users` and `roles` in so many words. The same
section grants `DELETE ON role_permissions, user_roles` — *"grant/revoke is real"* — so the blanket
rule needs one exception, and the exception is **named** rather than the rule being replaced by a
one-table allow-list: a table added later is covered the day it lands, not the day someone remembers
to list it. `test_the_hard_delete_exception_is_the_designs_grant` keeps the carve-out no wider than
the design's grant, and `test_the_no_hard_delete_rule_covers_real_tenant_tables` keeps the rule from
going vacuous.
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

# The one exception the design names: a revoke is a real `DELETE` on these two link tables
# (`03-users-and-roles/03-design.md` §Database privileges — *"grant/revoke is real"*). Every other
# table carrying a `tenant_id` keeps neither `DELETE` nor `TRUNCATE` for the application role, and
# stays covered when it is added.
LINK_TABLES_WITH_A_DESIGNED_DELETE = ("role_permissions", "user_roles")

_LINK_TABLE_LIST_SQL = ", ".join(
    f"'{table}'" for table in LINK_TABLES_WITH_A_DESIGNED_DELETE
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
_APP_DELETE_OR_TRUNCATE_ON_A_TENANT_TABLE = text(
    "SELECT g.table_name, g.privilege_type "
    "FROM information_schema.role_table_grants g "
    "WHERE g.grantee = 'clinos_app' AND g.privilege_type IN ('DELETE', 'TRUNCATE') "
    "AND EXISTS ("
    "  SELECT 1 FROM information_schema.columns c "
    "  WHERE c.table_schema = g.table_schema AND c.table_name = g.table_name "
    "    AND c.column_name = 'tenant_id'"
    ")"
    f"AND g.table_name NOT IN ({_LINK_TABLE_LIST_SQL})"
)
_IS_TENANT_TABLE = text(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = 'public' AND table_name = :table AND column_name = 'tenant_id'"
)
_TENANT_TABLES = text(
    "SELECT DISTINCT table_name FROM information_schema.columns "
    "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
)
_GRANTS_FOR_APP_ON = text(
    "SELECT privilege_type FROM information_schema.role_table_grants "
    "WHERE grantee = 'clinos_app' AND table_name = :table"
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
    """R14 / the no-hard-delete rule, across every tenant table but the design's one exception.

    The exception is the two RBAC link tables: the design grants `DELETE` on them so a revoke is
    real, and `test_users_roles_isolation.py` asserts that grant exists. Every *other* tenant table
    is checked, so a table that gains `DELETE` — or that is added later and granted it — fails here
    without anyone having to remember a list.
    """
    with engine.connect() as conn:
        rows = conn.execute(_APP_DELETE_OR_TRUNCATE_ON_A_TENANT_TABLE).all()
    assert rows == [], (
        "`clinos_app` holds DELETE or TRUNCATE on a tenant table outside the design's carve-out: "
        + ", ".join(f"{table}.{privilege}" for table, privilege in rows)
    )


def test_the_hard_delete_exception_is_the_designs_grant() -> None:
    """The carve-out is exactly the design's two link tables, and it is not silent.

    `03-design.md` §Database privileges is the only thing that authorises a `DELETE` for the
    application role. If the exception list is widened without that grant, or the grant disappears
    while the exception stays, this fails.
    """
    assert LINK_TABLES_WITH_A_DESIGNED_DELETE == ("role_permissions", "user_roles"), (
        "the hard-delete carve-out is no longer the design's grant; the rule above is now testing "
        "something the design does not say"
    )
    with engine.connect() as conn:
        for table in LINK_TABLES_WITH_A_DESIGNED_DELETE:
            assert (
                conn.execute(_IS_TENANT_TABLE, {"table": table}).first() is not None
            ), (
                f"{table} is the hard-delete carve-out but is not a tenant table in `public`; the "
                "control is not testing what it names"
            )
            granted = {
                row[0] for row in conn.execute(_GRANTS_FOR_APP_ON, {"table": table})
            }
            assert "DELETE" in granted, (
                f"{table} is the design's carve-out but `clinos_app` holds no DELETE on it: "
                f"has {sorted(granted)}"
            )
            assert "TRUNCATE" not in granted, (
                f"`clinos_app` holds TRUNCATE on {table}; a revoke is a single-row delete, never a "
                "table wipe"
            )


def test_the_no_hard_delete_rule_covers_real_tenant_tables() -> None:
    """Keep the rule able to fail: the tables it exists to protect must still be covered.

    `user` is the legacy table the design calls `users`; `roles` and `patients` are the other tenant
    tables that exist today. If the carve-out ever widens to swallow one of these, the rule above
    goes quiet exactly where the no-hard-delete requirement bites.
    """
    with engine.connect() as conn:
        tenant_tables = {row[0] for row in conn.execute(_TENANT_TABLES)}
    covered = tenant_tables - set(LINK_TABLES_WITH_A_DESIGNED_DELETE)
    assert covered, (
        "no tenant table is covered by the no-DELETE rule, so the assertion above can never fire"
    )
    assert {"user", "roles", "patients"} <= covered, (
        "the no-DELETE rule no longer covers the tenant tables it exists to protect; covered "
        f"tables are {sorted(covered)}"
    )
