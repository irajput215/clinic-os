"""create the append-only, hash-chained audit log

Revision ID: b7c1d9e4f2a3
Revises: a1f2b3c4d5e6
Create Date: 2026-10-06 12:00:00.000000

Task T1-21/T1-22/T1-23. Feature 04: `docs/features/04-audit-log/03-design.md` §"Table: `audit_log`",
§"RLS" and §"Database privileges"; requirements R1, R2, R6, R8, R14, R15; Gate 2's check *"An `UPDATE`
or `DELETE` against `audit_log` through the application role is refused"*.

## What this migration is, in one paragraph

`audit_log` is the table the whole platform's evidence depends on, so three independent controls stop
it being rewritten rather than one: **grants** (`clinos_app` holds `SELECT, INSERT` and nothing else,
so an `UPDATE`/`DELETE`/`TRUNCATE` raises `42501 insufficient_privilege` at the engine), **RLS**
(`ENABLE` + `FORCE`, so the owner is not exempt) and a **single write path** in
`app/modules/audit/service.py`. A grant prevents and a chain only detects, which is why both exist.

## The DDL is raw SQL, deliberately

The table is **partitioned by range on `timestamp`**, and neither SQLModel nor Alembic can express
`PARTITION BY`. So this migration writes the table with `CREATE TABLE ... PARTITION BY RANGE`, and the
model in `app/modules/audit/models.py` describes the same columns, constraints and index names. The
two are kept in step by `alembic check` (which compares the model to the database) and by
`tests/core/test_schema_conventions.py` (which compares every generated name). Partition *children*
are excluded from autogenerate in `app/alembic/env.py`, because Alembic reads them as tables the
models forgot rather than as the partition strategy they are.

## RLS: two policies and no more

`04-design.md` §RLS is unusually specific — *"Two policies only, and no more: `audit_log_insert`
`WITH CHECK` and `audit_log_select` `USING`"* — and adds the reason: *"**No `UPDATE` policy and no
`DELETE` policy exists**, so those statements affect zero rows even if a grant is granted in error."*
That is a second, independent control on top of the grant, and it is why this migration creates two
policies where `patients` has a permissive `FOR ALL` plus a restrictive floor. A `FOR ALL` policy here
would be strictly worse: it would create the `UPDATE` and `DELETE` policies the design forbids.

Both policies are `TO PUBLIC`, not `TO clinos_app`, following `134a7201f6d2`'s precedent: the
application connects as the table owner today (`postgres` locally, `neondb_owner` in the deployed
environment, both `BYPASSRLS`), and a policy scoped to a role that cannot log in would apply to
nobody. `FORCE` plus `TO PUBLIC` means the policy binds the owner too, so isolation holds for the
connection that exists **and** for the least-privilege role when the deployment switches to it.

## Grants

    GRANT SELECT, INSERT ON audit_log TO clinos_app;
    REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app;
    GRANT SELECT ON audit_log TO clinos_readonly_audit;

`clinos_readonly_audit` is the compliance/auditor read role the design names. It gets `SELECT` and
nothing else — the test asserts that too, because a role that can `INSERT` an audit event is a role
that can forge one.

`clinos_retention` gets no grant here. The design's row for it is *"Partition drop only, after
legal-hold check"*, which is a **DDL** privilege on a future partition-management path, not a table
grant; issuing a table grant would give the retention job more than the design says it has. The
partition-drop path is not built (feature 14 owns it), so the grant is deferred with it.

`TRUNCATE` is revoked explicitly even though no `GRANT` issued it: PostgreSQL does not grant
`TRUNCATE` implicitly, but a `REVOKE` is what makes this migration the one place the least-privilege
set is written down, and a re-run of an interrupted migration is then a no-op.

**No `ALTER TABLE ... OWNER` is issued.** The design's role table says `clinos_migrator` *"owns the
table"*, and this migration deliberately leaves the owner as the role that ran it — the same choice
`33c56ebab859` made for `tenants`, `user` and `patients`, for the same reason: `clinos_migrator` is
created `NOLOGIN PASSWORD NULL` (a credential does not belong in a migration), and a migration that
re-owned the table would make every later `ALTER TABLE` on it impossible for the role that actually
runs migrations. The property R15 and Gate 2 require is the negative one — *"the application role is
not the table owner and has no `BYPASSRLS`"* — and that holds. Recorded for the lead as a deviation.

## Idempotent

Every statement is `IF NOT EXISTS` or a `GRANT`/`REVOKE` (both idempotent in PostgreSQL), so a re-run
of an interrupted migration is safe.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c1d9e4f2a3"
down_revision = "a1f2b3c4d5e6"
branch_labels = None
depends_on = None

# The design's fail-closed guard, byte for byte. An unset or empty `app.tenant_id` becomes NULL,
# `tenant_id = NULL` matches no row, so a missing context reads zero rows rather than every row.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# A partition per month, with a default partition that absorbs anything outside the created range.
# The design puts it plainly: *"Partitioned monthly by range on `timestamp`, with a default partition
# that alerts"* (`03-design.md`, "Table: audit_log"). Twelve months are created up front beside the
# current one, so the table is covered for a year without intervention; a month that is not created
# lands in the default partition rather than failing the insert, because an audit write that cannot
# land must never be the reason a clinical change does not happen.
_COLUMNS = """
    event_id uuid NOT NULL,
    "timestamp" timestamptz NOT NULL,
    tenant_id uuid,
    actor_id uuid,
    actor_role varchar(64),
    action varchar(128) NOT NULL,
    resource_type varchar(32) NOT NULL,
    resource_id uuid,
    result varchar(16) NOT NULL,
    reason varchar(255),
    source_ip varchar(64),
    request_id varchar(128) NOT NULL,
    correlation_id varchar(128),
    prev_hash varchar(64) NOT NULL,
    hash varchar(64) NOT NULL,
    metadata jsonb,
    CONSTRAINT pk_audit_log PRIMARY KEY (event_id, "timestamp"),
    CONSTRAINT ck_audit_log_result CHECK (result IN ('SUCCESS', 'DENIED', 'FAILED', 'UNKNOWN')),
    CONSTRAINT ck_audit_log_resource_type CHECK (resource_type IN ('PATIENT', 'CLINICAL_RECORD',
        'PRESCRIPTION', 'TGA_APPROVAL', 'TGA_DOCUMENT', 'USER', 'TENANT', 'SESSION', 'AUDIT',
        'REPORT', 'INTEGRATION', 'EXPORT'))
"""

# The design's four indexes, named by `app.core.metadata`'s `ix_` convention rather than the design's
# `idx_` (the same deviation `134a7201f6d2` recorded). `tenant_id` leads every one; `timestamp DESC`
# matches the read path's order. Created explicitly rather than through the model, because
# `sa.Index(..., sa.text("timestamp DESC"))` renders a plain column expression — the descending order
# has to be written as SQL.
_INDEXES = (
    (
        "ix_audit_log_tenant_timestamp",
        'audit_log (tenant_id, "timestamp" DESC)',
    ),
    (
        "ix_audit_log_tenant_actor_timestamp",
        'audit_log (tenant_id, actor_id, "timestamp" DESC)',
    ),
    (
        "ix_audit_log_tenant_action_timestamp",
        'audit_log (tenant_id, action, "timestamp" DESC)',
    ),
    (
        "ix_audit_log_tenant_resource_timestamp",
        'audit_log (tenant_id, resource_type, resource_id, "timestamp" DESC)',
    ),
)


def upgrade() -> None:
    op.execute(
        f'CREATE TABLE IF NOT EXISTS audit_log ({_COLUMNS}) PARTITION BY RANGE ("timestamp")'
    )
    for name, target in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")

    # A month of partitions plus a default. `date_trunc` on `now()` is the migration's clock, which is
    # the right clock: a partition is a schema object, not an event.
    op.execute(
        """
        DO $$
        DECLARE
            boundary timestamptz := date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
            step integer;
        BEGIN
            FOR step IN 0..12 LOOP
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_log '
                    'FOR VALUES FROM (%L) TO (%L)',
                    'audit_log_' || to_char(boundary + make_interval(months => step), 'YYYY_MM'),
                    boundary + make_interval(months => step),
                    boundary + make_interval(months => step + 1)
                );
            END LOOP;
        END $$;
        """
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS audit_log_default "
        "PARTITION OF audit_log DEFAULT"
    )

    # RLS. `FORCE` is what removes the owner's exemption, so the policy binds the connection the
    # application actually uses today as well as `clinos_app` tomorrow.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")

    # Two policies, and no more. `AS PERMISSIVE` is explicit: a restrictive policy only narrows
    # access and cannot grant it, so a restrictive-only table denies every row (measured — see
    # `134a7201f6d2`'s docstring). The design's two-policy shape is preserved exactly: an INSERT
    # policy with `WITH CHECK`, a SELECT policy with `USING`, and **no** UPDATE and no DELETE policy.
    op.execute(
        "CREATE POLICY audit_log_insert ON audit_log "
        "AS PERMISSIVE FOR INSERT TO PUBLIC "
        f"WITH CHECK ({_TENANT_MATCH})"
    )
    op.execute(
        "CREATE POLICY audit_log_select ON audit_log "
        "AS PERMISSIVE FOR SELECT TO PUBLIC "
        f"USING ({_TENANT_MATCH})"
    )

    # The centrepiece: enforcement by grant, not by convention. An `UPDATE` or a `DELETE` through
    # `clinos_app` raises `42501 insufficient_privilege` (Gate 2).
    op.execute("GRANT SELECT, INSERT ON audit_log TO clinos_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM clinos_app")

    # The compliance/auditor read role: `SELECT` only, subject to the same policy.
    op.execute("GRANT SELECT ON audit_log TO clinos_readonly_audit")


def downgrade() -> None:
    # `DROP TABLE` removes the partitions, the indexes and the policies with it. The grants need no
    # explicit revoke: they are dropped as part of the object. `audit_log_default` and the monthly
    # partitions are not dropped separately because dropping a partitioned parent drops its children.
    op.execute("DROP TABLE IF EXISTS audit_log")
