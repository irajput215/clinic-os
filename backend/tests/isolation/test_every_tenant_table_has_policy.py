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

# `audit_log` is **partitioned by range on `timestamp`** (`04-audit-log/03-design.md`, "Table:
# audit_log"), so PostgreSQL lists both the partitioned parent and each monthly partition as a
# relation carrying every column. Only the parent is the table the design describes and the object
# the policies are created on; a partition inherits its parent's row-level security rather than
# declaring its own. Both are therefore reported by the discovery below, and both are checked — the
# parent through the trio of enable/force/policy, the child through the parent it inherits from.
_DISCOVER_TENANT_TABLES = text(
    "SELECT c.relname, col.is_nullable, c.relkind "
    "FROM information_schema.columns col "
    "JOIN pg_class c ON c.relname = col.table_name "
    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = col.table_schema "
    "WHERE col.table_schema = 'public' AND col.column_name = 'tenant_id' "
    "AND c.relkind IN ('r', 'p')"
)
_RLS_STATE = text(
    "SELECT c.relrowsecurity, c.relforcerowsecurity, c.relkind "
    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relname = :table AND c.relkind IN ('r', 'p')"
)
_POLICY_NAMES = text(
    "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = :table"
)
_PARENT_OF_A_PARTITION = text(
    "SELECT parent.relname, parent.relrowsecurity, parent.relforcerowsecurity "
    "FROM pg_inherits i "
    "JOIN pg_class child ON child.oid = i.inhrelid "
    "JOIN pg_class parent ON parent.oid = i.inhparent "
    "JOIN pg_namespace n ON n.oid = child.relnamespace "
    "WHERE n.nspname = 'public' AND child.relname = :table"
)


def _isolation_problems(conn) -> list[str]:
    """Every tenant-scoped relation that is not isolated, in the words of what is missing."""
    discovered = {row[0]: row[1] for row in conn.execute(_DISCOVER_TENANT_TABLES)}
    problems: list[str] = []

    for table in sorted(set(discovered) - set(_NOT_YET_TENANT_SCOPED)):
        state = conn.execute(_RLS_STATE, {"table": table}).one_or_none()
        assert state is not None, f"{table} has a tenant_id but no table in pg_class"
        parent = conn.execute(_PARENT_OF_A_PARTITION, {"table": table}).one_or_none()
        if parent is not None:
            # A partition cannot declare its own policy: it inherits the parent's. What has to hold
            # is that the parent is enabled, forced and policied, which the parent's own turn
            # through this loop asserts. A partition whose parent is missing from the discovery is
            # still a problem, and is reported as one.
            parent_name, parent_rls, parent_forced = parent
            if parent_name not in discovered:
                problems.append(
                    f"{table}: a partition of {parent_name}, which carries no tenant_id and is "
                    "therefore never checked — the partition is not proven isolated"
                )
            elif not (parent_rls and parent_forced):
                problems.append(
                    f"{table}: a partition of {parent_name}, which is not both ENABLED and FORCED"
                )
            continue

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
    return problems


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

        problems = _isolation_problems(conn)

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

    # What this test is really asking is "is any nullable tenant key table left with **no** isolation
    # control at all?". Two kinds of table are not that: the recorded exemptions, and a partition
    # child, which does not declare the row-level security it enforces (its parent declares it, and
    # `test_every_tenant_table_has_a_forced_policy` checks the parent). A table that is row-secured is
    # also not a problem — `audit_log` has a nullable `tenant_id` **on purpose** (platform-level
    # events are design OPEN-7) and is enabled and forced, which the test above proves.
    with engine.connect() as conn:
        unexpected: list[str] = []
        for table, nullable in discovered.items():
            if nullable != "YES" or table in _NOT_YET_TENANT_SCOPED:
                continue
            if conn.execute(_PARENT_OF_A_PARTITION, {"table": table}).one_or_none():
                continue
            if not conn.execute(_RLS_STATE, {"table": table}).one()[0]:
                unexpected.append(table)
        unexpected.sort()
    assert not unexpected, (
        "These tables carry a nullable `tenant_id`, are not row-secured, and are neither recorded "
        f"in _NOT_YET_TENANT_SCOPED nor partitions of a row-secured parent: {unexpected}"
    )
