"""create clinics with forced row-level security and least-privilege grants

Revision ID: 3aec419d218b
Revises: a1f2b3c4d5e6
Create Date: 2026-10-06 10:09:43.548372

Task T1-01 Part B. `clinics` is the tenant-scoped child of `tenants`: one organisation, several practice
sites (`docs/features/01-tenancy-and-clinics/03-design.md`, "Table: `clinics` (tenant-scoped)").

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
`clinos_migrator` taking ownership is the design's line and the completion of the deferral recorded in
`33c56ebab859_database_roles.py` (*"it owns `clinics` and `audit_log` when those migrations land"*).
`clinos_app` never owns a table, and `clinos_migrator` is `NOLOGIN` with a null password, so ownership
confers no reachable privilege — it exists so the running application role is never the owner.

**Production note.** `ALTER TABLE ... OWNER TO` requires the migration role to be a superuser or a
member of `clinos_migrator`. That holds for every environment this repository migrates today (CI and
local both run as `postgres`); a deployment that migrates as a lesser role fails here loudly rather than
skipping the ownership line silently.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '3aec419d218b'
down_revision = 'a1f2b3c4d5e6'
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

    # `clinos_app` never owns a table. Ownership by the NOLOGIN migrator role is what the design
    # specifies and what 33c56ebab859 deferred to this migration.
    op.execute('ALTER TABLE clinics OWNER TO clinos_migrator')


def downgrade():
    # Ownership returns to the role running the migration before the table is dropped: `drop_table`
    # would work either way as a superuser, but a downgrade that leaves the cluster with an owner
    # nobody can address is a worse state than the one it started from.
    op.execute('ALTER TABLE clinics OWNER TO CURRENT_USER')
    op.execute('DROP POLICY pol_clinics_tenant_isolation ON clinics')
    op.execute('DROP POLICY pol_clinics_tenant_access ON clinics')
    op.execute('ALTER TABLE clinics NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE clinics DISABLE ROW LEVEL SECURITY')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON clinics FROM clinos_app')
    op.drop_table('clinics')
