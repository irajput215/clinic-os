"""create clinics with forced row-level security and least-privilege grants

Revision ID: 3aec419d218b
Revises: b7c1d9e4f2a3
Create Date: 2026-10-06 10:09:43.548372

Task T1-01 Part B. `clinics` is the tenant-scoped child of `tenants`: one organisation, several practice
sites (`docs/features/01-tenancy-and-clinics/03-design.md`, "Table: `clinics` (tenant-scoped)").

**Single migration head.** This revision originally descended from `a1f2b3c4d5e6`; the audit-log migration
`b7c1d9e4f2a3` was merged from `main` and descends from the same parent, which left two heads. Alembic
refuses to upgrade a database with more than one head, so this chain is re-pointed at the audit head:
`a1f2b3c4d5e6` → `b7c1d9e4f2a3` → `3aec419d218b` → `1a1af875311b` → `fbcebceb0686`.

The policy is the design's, and the reason it is created here rather than in the model is the same as
for `patients`: a model cannot express `CREATE POLICY`, and a database built from
`SQLModel.metadata.create_all` would otherwise get a table that looks right and enforces nothing.

    CREATE POLICY pol_clinics_tenant_isolation ON clinics
      AS RESTRICTIVE FOR ALL TO clinos_app, clinos_readonly_audit, clinos_retention
      USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

## Two deliberate deviations from that statement, both recorded

1. **A permissive policy accompanies the restrictive floor.** A restrictive policy only narrows access;
   it cannot grant it. Measured on `patients` (the migration before this one): with the restrictive
   policy as the only policy, a non-superuser role with the correct `app.tenant_id` still saw zero
   rows. `pol_clinics_tenant_access` is therefore the policy that grants a caller its own rows, and
   `pol_clinics_tenant_isolation` is kept exactly as the design specifies as the floor that stops a
   permissive policy added later from widening past the tenant boundary.

2. **The policies apply `TO PUBLIC`, not to the three role names.** The design names `clinos_app`,
   `clinos_readonly_audit` and `clinos_retention` as the roles the policy applies to. The application
   still connects as the table owner (`postgres` locally, `neondb_owner` in the deployment), and a
   policy restricted to those three names would apply to nobody — with RLS forced, that denies the
   application every row including its own. `TO PUBLIC` enforces the boundary for the connection that
   exists today *and* for the least-privilege roles when the deployment switches to them. No role is
   granted a privilege here that the design does not name.

## Grants — the design's "no DELETE where retention may apply", verbatim

    GRANT SELECT, INSERT, UPDATE ON clinics TO clinos_app;
    REVOKE DELETE, TRUNCATE ON clinics FROM clinos_app;
    ALTER TABLE clinics OWNER TO clinos_migrator;

`REVOKE DELETE, TRUNCATE` removes nothing (neither was ever granted) and is what makes the rule hold if
a later grant adds one by mistake; `tests/isolation/test_app_role_is_not_owner.py` asserts the absence
for every tenant table, and `tests/security/test_tenant_grants.py` asserts this table's exact grant set.
The third line is the one deviation, and it is the next section.

## `ALTER TABLE clinics OWNER TO clinos_migrator` is deliberately **not** issued

This migration originally issued it, reading `33c56ebab859_database_roles.py` (*"it owns `clinics` and
`audit_log` when those migrations land"*) as a deferral to complete here. **That line broke the
deployment, and it is removed.** It passed every check this repository runs and failed only in
production, so the evidence is recorded rather than the conclusion:

* `ALTER TABLE ... OWNER TO` requires the migration role to be a superuser **or a member of the target
  role**, and the target role must itself hold `CREATE` on the table's schema.
* CI and local migrate as `postgres`, a superuser, so both conditions hold and the migration is green —
  which is exactly why nothing caught this before it shipped.
* The deployment migrates as Neon's `neondb_owner`: `MIGRATION_DATABASE_URL` is unset, so it falls back
  to `DATABASE_URL`, and no separate migration credential exists yet. That role is neither a superuser
  nor a member of `clinos_migrator`, so the step failed with `InsufficientPrivilege: must be able to SET
  ROLE "clinos_migrator"`. It failed before `fastapi deploy`, so nothing shipped and the migration —
  being transactional — rolled back: the failure was total and loud, not partial.
* Reproduced outside CI by migrating an empty database as a non-superuser role holding `CREATEROLE` and
  `BYPASSRLS`, which is `neondb_owner`'s shape. With this one line removed the whole chain runs to
  `head` with no other error, so it was the only blocker in the merged chain — not the first of several.

`33c56ebab859` and `b7c1d9e4f2a3` (the audit log) faced the same design line and reached the same
conclusion, recording it as a deviation: *"a migration that re-owned the table would make every later
`ALTER TABLE` on it impossible for the role that actually runs migrations."* This migration now matches
them. What the design actually requires of the tables that exist is the negative property — R15 and
Gate 2's *"the application role is not the table owner and has no `BYPASSRLS`"* — and that still holds:
the owner is the role that ran the migration, and `clinos_app` owns nothing. `clinos_migrator` remains
`NOLOGIN PASSWORD NULL`, so the ownership it would have taken conferred no reachable privilege today;
what it changed was the deployment's ability to migrate at all.

**Raised, not settled.** Whether `clinos_migrator` should own the domain tables is a decision this
repository has not taken. Taking it needs a migration credential that is a member of that role
(`GRANT clinos_migrator TO <deployment role>`) and `CREATE` on schema `public` for it — two grants, both
production-affecting, neither of them named by the design.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '3aec419d218b'
down_revision = 'b7c1d9e4f2a3'
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy name or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade():
    op.create_table('clinics',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('address', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_clinics_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clinics')),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_clinics_tenant_id_id'),
    sa.UniqueConstraint('tenant_id', 'name', name='uq_clinics_tenant_id_name')
    )

    # The application role. Least privilege is the point: no SUPERUSER, no BYPASSRLS, and it owns
    # nothing. `clinos_app` already exists (134a7201f6d2 created it) and already has USAGE on the
    # schema; neither is re-issued here.
    op.execute('GRANT SELECT, INSERT, UPDATE ON clinics TO clinos_app')
    # No DELETE and no TRUNCATE: the design's "no DELETE where retention may apply". Ending the
    # life of a clinic is OPEN (retention for `tenants`, `clinics` and `tenant_settings` is
    # REQUIRES LEGAL/REGULATORY VALIDATION), so the capability is withheld until it is decided.
    op.execute('REVOKE DELETE, TRUNCATE ON clinics FROM clinos_app')

    # The isolation boundary. `ENABLE` turns the policy on; `FORCE` applies it to the table owner too.
    op.execute('ALTER TABLE clinics ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE clinics FORCE ROW LEVEL SECURITY')
    # A permissive policy is what actually grants a caller its own rows (see the module docstring).
    op.execute(
        'CREATE POLICY pol_clinics_tenant_access ON clinics '
        'AS PERMISSIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )
    # The design's policy, kept as specified: the restrictive floor.
    op.execute(
        'CREATE POLICY pol_clinics_tenant_isolation ON clinics '
        'AS RESTRICTIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )

    # `clinos_app` never owns a table (R15, Gate 2). Ownership is left with the role that runs this
    # migration: the design's `ALTER TABLE clinics OWNER TO clinos_migrator` is deliberately not
    # issued here — see the module docstring for the deployment failure that settled it.


def downgrade():
    # Ownership returns to the role running the migration before the table is dropped. That is a no-op
    # for a database built by this revision, and it is kept for one built by the previous revision,
    # which did issue the `OWNER TO clinos_migrator` this file no longer issues. `drop_table` would
    # work either way as a superuser, but a downgrade that leaves the cluster with an owner nobody can
    # address is a worse state than the one it started from.
    op.execute('ALTER TABLE clinics OWNER TO CURRENT_USER')
    op.execute('DROP POLICY pol_clinics_tenant_isolation ON clinics')
    op.execute('DROP POLICY pol_clinics_tenant_access ON clinics')
    op.execute('ALTER TABLE clinics NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE clinics DISABLE ROW LEVEL SECURITY')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON clinics FROM clinos_app')
    op.drop_table('clinics')
