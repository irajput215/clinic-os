"""T1-11 — the application role owns nothing, bypasses nothing, and cannot delete a clinical row.

`FORCE ROW LEVEL SECURITY` closes the owner exemption and nothing else. A role holding `BYPASSRLS`
reads every row with every policy in place, and an owner can drop the policy that constrains it, so
`clinos_app` must be neither. These assertions read `pg_roles`, `pg_class` and
`information_schema.role_table_grants` after the migrations — the grant listing, not the migration
source, is the evidence.

The roles are created `NOLOGIN PASSWORD NULL` on purpose: a credential does not belong in a
migration and cannot be rotated from one, so the deployment sets it out of band. That is why
`rolcanlogin` is asserted false here rather than a password being checked.

**The no-DELETE control is a named allow-list, not "every tenant table".** Requirement R11 —
*"A user is deactivated, not hard-deleted; clinical attribution survives"* — is a **clinical-data**
rule. It does not generalise: `03-users-and-roles/03-design.md` §Database privileges grants
`clinos_app` `DELETE ON role_permissions, user_roles` — *"grant/revoke is real"* — so a blanket
"no DELETE on any table carrying a `tenant_id`" would forbid the design's own revocation path. The
allow-list names the tables the rule actually protects, and
`test_the_clinical_no_delete_list_names_real_tenant_tables` keeps the list from going vacuous. Adding
`DELETE` to a table on the list fails this file; adding it to the two RBAC link tables does not.
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

# The clinical tables that must never gain `DELETE` or `TRUNCATE` for the application role. This is
# the rule requirement R11 depends on, narrowed from "any table with a tenant_id" to the tables it is
# about. New clinical tables are added here as they land.
CLINICAL_TABLES_WITHOUT_HARD_DELETE = ("patients",)

_CLINICAL_TABLE_LIST_SQL = ", ".join(
    f"'{table}'" for table in CLINICAL_TABLES_WITHOUT_HARD_DELETE
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
_APP_DELETE_OR_TRUNCATE_ON_A_CLINICAL_TABLE = text(
    "SELECT g.table_name, g.privilege_type "
    "FROM information_schema.role_table_grants g "
    "WHERE g.grantee = 'clinos_app' AND g.privilege_type IN ('DELETE', 'TRUNCATE') "
    f"AND g.table_name IN ({_CLINICAL_TABLE_LIST_SQL})"
)
_IS_TENANT_TABLE = text(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = 'public' AND table_name = :table AND column_name = 'tenant_id'"
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


def test_the_app_role_holds_no_delete_or_truncate_on_a_clinical_table() -> None:
    """R11 / the no-hard-delete rule, for the clinical tables it is actually about.

    The two RBAC link tables are deliberately **not** on the list: the design grants `DELETE` on
    them so a role can be revoked (`03-design.md`, "grant/revoke is real"), and
    `test_users_roles_isolation.py` asserts that grant exists.
    """
    with engine.connect() as conn:
        rows = conn.execute(_APP_DELETE_OR_TRUNCATE_ON_A_CLINICAL_TABLE).all()
    assert rows == [], (
        "`clinos_app` holds DELETE or TRUNCATE on a clinical table: "
        + ", ".join(f"{table}.{privilege}" for table, privilege in rows)
    )


def test_the_clinical_no_delete_list_names_real_tenant_tables() -> None:
    """Keep the narrowed control able to fail: an empty or wrong list would pass every time."""
    assert CLINICAL_TABLES_WITHOUT_HARD_DELETE, (
        "the clinical no-DELETE allow-list is empty, so the control above can never fire"
    )
    with engine.connect() as conn:
        for table in CLINICAL_TABLES_WITHOUT_HARD_DELETE:
            assert (
                conn.execute(_IS_TENANT_TABLE, {"table": table}).first() is not None
            ), (
                f"{table} is on the clinical no-DELETE list but is not a tenant table in "
                "`public`; the control is not testing what it names"
            )
