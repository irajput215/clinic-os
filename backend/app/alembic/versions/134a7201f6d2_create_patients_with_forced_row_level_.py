"""create patients with forced row-level security

Revision ID: 134a7201f6d2
Revises: f993c55e6eaf
Create Date: 2026-10-05 18:14:23.493455

`patients` is the first tenant-scoped table, so this migration also carries the first row-level
security policy. The policy cannot live in the model: a model cannot express `CREATE POLICY`, and a
database built from `SQLModel.metadata.create_all` would otherwise get a table that looks correct and
enforces nothing.

The expressions are the design's (`docs/features/05-patients/03-design.md`, §RLS), including the
`NULLIF` that makes it fail closed: an unset or empty `app.tenant_id` becomes `NULL`, `tenant_id = NULL`
matches no row, so a missing tenant context returns **zero rows rather than every row**. `FORCE` is what
makes that true for the table owner as well as for everyone else.

**Deliberate deviation — the policy applies to `PUBLIC`, not `TO clinos_app`.** The design names
`clinos_app`: a non-owner role with no `BYPASSRLS`, which the application is expected to connect as.
That role does not exist yet (task T1-11) and the application connects as the table owner, so a policy
restricted to `clinos_app` would apply to nobody — and with RLS forced, that denies the application
every row including its own. Applying the policy to `PUBLIC` with `FORCE` enforces isolation for the
connection that exists today. The least-privilege role split, with the no-`DELETE` grant that R11
depends on, remains outstanding. Recorded in `docs/progress.md` §4.

Index names follow the repository's `ix_` prefix rather than the design's `idx_`, because
`app.core.metadata` is the single place index naming is decided.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '134a7201f6d2'
down_revision = 'f993c55e6eaf'
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy name or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade():
    op.create_table('patients',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('given_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('family_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('preferred_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=False),
    sa.Column('sex_at_birth', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('gender_identity', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('medicare_number', sa.LargeBinary(), nullable=True),
    sa.Column('medicare_blind_index', sa.LargeBinary(), nullable=True),
    sa.Column('ihi', sa.LargeBinary(), nullable=True),
    sa.Column('ihi_blind_index', sa.LargeBinary(), nullable=True),
    sa.Column('address_line', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('suburb', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('state', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('postcode', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('deceased_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('merged_into_patient_id', sa.Uuid(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("sex_at_birth IN ('FEMALE', 'MALE', 'INTERSEX', 'UNKNOWN')", name=op.f('ck_patients_sex_at_birth')),
    sa.ForeignKeyConstraint(['merged_into_patient_id'], ['patients.id'], name=op.f('fk_patients_merged_into_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_patients_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_patients')),
    sa.UniqueConstraint('tenant_id', 'id', name='uq_patients_tenant_id_id')
    )
    op.create_index('ix_patients_tenant_active', 'patients', ['tenant_id'], unique=False, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index('ix_patients_tenant_dob', 'patients', ['tenant_id', 'date_of_birth'], unique=False)
    op.create_index('ix_patients_tenant_family_name', 'patients', ['tenant_id', 'family_name', 'given_name'], unique=False)
    op.create_index('ix_patients_tenant_ihi_blind_index', 'patients', ['tenant_id', 'ihi_blind_index'], unique=False)
    op.create_index('ix_patients_tenant_medicare_blind_index', 'patients', ['tenant_id', 'medicare_blind_index'], unique=False)

    # The application role. Least privilege is the point: no SUPERUSER, no BYPASSRLS, and it owns
    # nothing. `BYPASSRLS` is what makes a policy decorative — the deployment's existing role
    # (`neondb_owner`, and `postgres` locally) both have it, so RLS was enforced for neither.
    #
    # NOLOGIN, deliberately: a password does not belong in a migration and cannot be rotated from one.
    # The deployment gives this role a credential out of band when the application is switched to it.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'clinos_app') THEN "
        "CREATE ROLE clinos_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE; "
        "END IF; END $$"
    )
    op.execute('GRANT USAGE ON SCHEMA public TO clinos_app')
    # No DELETE and no TRUNCATE: requirement R11 — a patient record is never hard-deleted by the
    # application — is enforced by grant rather than by convention.
    op.execute('GRANT SELECT, INSERT, UPDATE ON patients TO clinos_app')

    # The isolation boundary. `ENABLE` turns the policy on; `FORCE` applies it to the table owner too, so
    # it cannot be sidestepped by owning the table.
    op.execute('ALTER TABLE patients ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE patients FORCE ROW LEVEL SECURITY')
    # A permissive policy is what actually grants a caller its own rows. A restrictive policy only
    # narrows access and cannot grant it, so restrictive alone denies every row — measured, not assumed:
    # with the policy below as the only policy, a non-superuser role with the correct `app.tenant_id`
    # set still saw zero rows. See the module docstring.
    op.execute(
        'CREATE POLICY pol_patients_tenant_access ON patients '
        'AS PERMISSIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )
    # The design's policy, kept as specified: a restrictive floor so a permissive policy added later
    # cannot widen what a caller can reach.
    op.execute(
        'CREATE POLICY pol_patients_tenant_isolation ON patients '
        'AS RESTRICTIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )


def downgrade():
    op.execute('DROP POLICY pol_patients_tenant_isolation ON patients')
    op.execute('DROP POLICY pol_patients_tenant_access ON patients')
    op.execute('ALTER TABLE patients NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE patients DISABLE ROW LEVEL SECURITY')
    op.drop_index('ix_patients_tenant_medicare_blind_index', table_name='patients')
    op.drop_index('ix_patients_tenant_ihi_blind_index', table_name='patients')
    op.drop_index('ix_patients_tenant_family_name', table_name='patients')
    op.drop_index('ix_patients_tenant_dob', table_name='patients')
    op.drop_index('ix_patients_tenant_active', table_name='patients', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('patients')
