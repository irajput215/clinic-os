"""create care_relationships with forced row-level security and least-privilege grants

Revision ID: 1a1af875311b
Revises: 3aec419d218b
Create Date: 2026-10-06 10:10:06.895715

Task T1-04 (Feature 03 R7). The table records the practitioner/patient treating relationship — the
authorisation input Feature 05's R7 and Feature 06's R11 both refuse a read without. Its column set is
the tuple both consumers name verbatim; the model carries the full provenance
(`app/modules/care_relationships/models.py`).

**No ERD defines this table.** `04-database-erd.md` has no `care_relationships`, which is why every
feature that reads it records the same open item ("named in `06-authentication-rbac.md` §10 but has no
ERD table definition"). This migration therefore follows the reasoning the repository already applies to
`patients`: the isolation controls are non-negotiable, and the shape is the tuple the consumers agree on,
with every choice that the source does not settle recorded in the model docstring rather than invented
silently.

## RLS, and the two deviations from the design's policy statement

The policy the design gives for every tenant table is a single restrictive policy:

    CREATE POLICY pol_care_relationships_tenant_isolation ON care_relationships
      AS RESTRICTIVE FOR ALL TO clinos_app
      USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

1. **A permissive policy accompanies it.** A restrictive policy narrows access; it cannot grant it. The
   `patients` migration measured the consequence — restrictive alone means every caller sees zero rows,
   including its own — so `pol_care_relationships_tenant_access` is the policy that grants a caller its
   own rows and the restrictive policy stays as the floor that stops a later permissive policy widening
   past the tenant boundary.
2. **`TO PUBLIC`, not `TO clinos_app`.** The application still connects as the table owner, and a policy
   restricted to a name it does not connect as would apply to nobody; with RLS forced that denies the
   application every row. `TO PUBLIC` enforces the boundary for today's connection and for the
   least-privilege role when the deployment switches to it.

`SET LOCAL app.tenant_id` (via `app.core.db.tenant_transaction`) is what sets the context the policy
reads; connection-pool reuse is covered by `tests/isolation/test_pool_reuse.py`.

## Grants

    GRANT SELECT, INSERT, UPDATE ON care_relationships TO clinos_app;
    REVOKE DELETE, TRUNCATE ON care_relationships FROM clinos_app;

`UPDATE` is what ends a relationship (`active_to`), so it is granted; `DELETE` is not, because an
authorisation record that can disappear is not evidence. No design section names this table's grants —
it has no ERD entry — so the set is derived from the design's rule for tables of this class
(`04-database-erd.md` §6: `SELECT, INSERT, UPDATE`, never `DELETE` where retention applies) and is
asserted by `tests/security/test_tenant_grants.py`. Ownership is left with the migrating role: the
design names `clinos_migrator` ownership for `clinics` and `audit_log` only, and inventing a third
would be a change to the role model rather than a schema detail.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '1a1af875311b'
down_revision = '3aec419d218b'
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy name or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade():
    op.create_table('care_relationships',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('practitioner_id', sa.Uuid(), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.Column('clinic_id', sa.Uuid(), nullable=True),
    sa.Column('active_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('active_to', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('active_to IS NULL OR active_to > active_from', name=op.f('ck_care_relationships_active_interval')),
    sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], name=op.f('fk_care_relationships_clinic_id_clinics'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_care_relationships_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['practitioner_id'], ['user.id'], name=op.f('fk_care_relationships_practitioner_id_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_care_relationships_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_care_relationships')),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_care_relationships_tenant_id_id')
    )
    op.create_index('ix_care_relationships_tenant_practitioner_patient', 'care_relationships', ['tenant_id', 'practitioner_id', 'patient_id'], unique=False)

    op.execute('GRANT SELECT, INSERT, UPDATE ON care_relationships TO clinos_app')
    op.execute('REVOKE DELETE, TRUNCATE ON care_relationships FROM clinos_app')

    op.execute('ALTER TABLE care_relationships ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE care_relationships FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY pol_care_relationships_tenant_access ON care_relationships '
        'AS PERMISSIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )
    op.execute(
        'CREATE POLICY pol_care_relationships_tenant_isolation ON care_relationships '
        'AS RESTRICTIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )


def downgrade():
    op.execute('DROP POLICY pol_care_relationships_tenant_isolation ON care_relationships')
    op.execute('DROP POLICY pol_care_relationships_tenant_access ON care_relationships')
    op.execute('ALTER TABLE care_relationships NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE care_relationships DISABLE ROW LEVEL SECURITY')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON care_relationships FROM clinos_app')
    op.drop_index('ix_care_relationships_tenant_practitioner_patient', table_name='care_relationships')
    op.drop_table('care_relationships')
