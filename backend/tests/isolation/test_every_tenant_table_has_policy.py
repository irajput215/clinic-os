"""T1-13 — every tenant table has a policy, and the policy is actually enforced.

A `tenant_id` column is not an isolation boundary. `ENABLE ROW LEVEL SECURITY` turns a policy on,
`FORCE ROW LEVEL SECURITY` applies it to the table owner too, and a policy is what grants a caller
its own rows. Any one of the three missing means the same thing: a raw query with no application
filter returns another tenant's rows, and nothing in the schema says so.

The table list is discovered, never hand-written — a hand-written list passes forever while a new
tenant table ships without a policy. `information_schema.columns` finds the tenant key, `pg_class`
answers whether RLS is on and forced, and `pg_policies` answers whether anything is granted at all.

Two tables that once made this test vacuous are guarded explicitly: the query must find `patients`
and must not find `tenants` (which has no `tenant_id`). A discovery query that matches nothing at
all would otherwise pass, which is the failure mode this test exists to prevent.
"""

from sqlalchemy import text

from app.core.db import engine

# A table may carry a `tenant_id` and still not be tenant-scoped today. Every exemption is named,
# with the reason, and asserted to be optional-tenant-key (`is_nullable = 'YES'`) by
# `test_the_exempt_tenant_tables_are_exactly_the_recorded_ones`: a `NOT NULL` tenant key is a tenant
# table by the design's own definition (`01-tenancy-and-clinics/03-design.md`) and has no excuse.
_NOT_YET_TENANT_SCOPED = {
    "user": (
        "`user.tenant_id` is nullable and the model documents it as 'a link rather than an "
        "isolation boundary'. RLS for the identity table is T1-03, blocked by D-003, and its "
        "target shape (`users`) does not exist yet. A tenant policy here today would also hide "
        "the platform administrator's own row before a tenant is resolved, breaking login."
    ),
}

_DISCOVER_TENANT_TABLES = text(
    "SELECT table_name, is_nullable FROM information_schema.columns "
    "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
)
_RLS_STATE = text(
    "SELECT c.relrowsecurity, c.relforcerowsecurity "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname = :table AND c.relkind = 'r'"
)
_POLICY_NAMES = text(
    "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = :table"
)


def test_every_tenant_table_has_a_forced_policy() -> None:
    """Fail closed: a tenant table without all three of enable, force and a policy is a breach."""
    with engine.connect() as conn:
        discovered = {row[0]: row[1] for row in conn.execute(_DISCOVER_TENANT_TABLES)}

        # Guard the discovery itself. Without this the test passes when the query returns nothing.
        assert "patients" in discovered, (
            "the tenant-table discovery did not find `patients`, so it is not testing anything: "
            f"it found {sorted(discovered)}"
        )
        assert discovered["patients"] == "NO"
        assert "tenants" not in discovered, (
            "`tenants` is global and has no `tenant_id`; finding it means the discovery is wrong"
        )

        problems: list[str] = []
        for table in sorted(set(discovered) - set(_NOT_YET_TENANT_SCOPED)):
            state = conn.execute(_RLS_STATE, {"table": table}).one_or_none()
            assert state is not None, (
                f"{table} has a tenant_id but no table in pg_class"
            )
            policies = [row[0] for row in conn.execute(_POLICY_NAMES, {"table": table})]
            if not state[0]:
                problems.append(f"{table}: ROW LEVEL SECURITY is not ENABLED")
            if not state[1]:
                problems.append(
                    f"{table}: ROW LEVEL SECURITY is not FORCED, so the table owner bypasses it"
                )
            if not policies:
                problems.append(
                    f"{table}: no policy exists, so nothing grants a caller its rows"
                )

    assert not problems, (
        "These tenant tables are not isolated by the database:\n  "
        + "\n  ".join(problems)
    )


def test_the_exempt_tenant_tables_are_exactly_the_recorded_ones() -> None:
    """Keep the exemption list honest, so it cannot grow into a place new tables hide."""
    with engine.connect() as conn:
        discovered = {row[0]: row[1] for row in conn.execute(_DISCOVER_TENANT_TABLES)}

    for table, reason in _NOT_YET_TENANT_SCOPED.items():
        assert table in discovered, f"{table} is exempt but has no tenant_id column"
        assert discovered[table] == "YES", (
            f"{table} is exempt, but its tenant_id is NOT NULL — a required tenant key is a tenant "
            f"table and must carry a forced policy. Recorded reason: {reason}"
        )

    unexpected = sorted(
        table
        for table, nullable in discovered.items()
        if nullable == "YES" and table not in _NOT_YET_TENANT_SCOPED
    )
    assert not unexpected, (
        "These tables carry a nullable `tenant_id` and are neither row-secured nor recorded in "
        f"_NOT_YET_TENANT_SCOPED: {unexpected}"
    )
