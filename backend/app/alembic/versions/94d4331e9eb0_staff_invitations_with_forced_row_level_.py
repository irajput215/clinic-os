"""staff invitations with forced row-level security

Revision ID: 94d4331e9eb0
Revises: 44c34ed0d6b2
Create Date: 2026-10-08 12:47:54.358178

Where each staff invitation stands, so Administration can show "Invited" and resend a link
(`docs/features/03-users-and-roles/03-design.md`, "As built: the `INVITED` status"). It is the interim
home of the design's `users.status = 'INVITED'`: `users` is T1-03 (blocked by D-003) and the legacy
`user` table is frozen.

A tenant table like every other: `ENABLE` and `FORCE ROW LEVEL SECURITY`, the permissive policy that
grants a caller its own tenant's rows and the restrictive one that keeps any later policy inside the
tenant, both on the `NULLIF` guard, `TO PUBLIC` for the reason `1a1af875311b` records (the application
still connects as the owner). `clinos_app` may read, insert and update a row (a resend and an
acceptance are updates) and never delete one.

**No backfill.** An account invited before this table existed cannot be told apart from one that
accepted (both have a password hash nobody can read), so it gets no row and lists as `ACTIVE`; its
link keeps working until it expires. The downgrade drops the table and loses only this derived state:
every link already sent still verifies against the account itself.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '94d4331e9eb0'
down_revision = '44c34ed0d6b2'
branch_labels = None
depends_on = None

# Raw SQL, so the naming convention cannot rewrite the policy name or the setting key.
_TENANT_MATCH = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade():
    op.create_table('staff_invitations',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('invited_by', sa.Uuid(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('pending_password_digest', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('expires_at > sent_at', name=op.f('ck_staff_invitations_expiry_after_send')),
    sa.ForeignKeyConstraint(['invited_by'], ['user.id'], name=op.f('fk_staff_invitations_invited_by_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_staff_invitations_tenant_id_tenants'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_staff_invitations_user_id_user'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_staff_invitations'))
    )
    op.create_index('ix_staff_invitations_tenant_id', 'staff_invitations', ['tenant_id'], unique=False)

    op.execute('GRANT SELECT, INSERT, UPDATE ON staff_invitations TO clinos_app')
    op.execute('REVOKE DELETE, TRUNCATE ON staff_invitations FROM clinos_app')

    op.execute('ALTER TABLE staff_invitations ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE staff_invitations FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY pol_staff_invitations_tenant_access ON staff_invitations '
        'AS PERMISSIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )
    op.execute(
        'CREATE POLICY pol_staff_invitations_tenant_isolation ON staff_invitations '
        'AS RESTRICTIVE FOR ALL TO PUBLIC '
        f'USING ({_TENANT_MATCH}) '
        f'WITH CHECK ({_TENANT_MATCH})'
    )


def downgrade():
    op.execute('DROP POLICY pol_staff_invitations_tenant_isolation ON staff_invitations')
    op.execute('DROP POLICY pol_staff_invitations_tenant_access ON staff_invitations')
    op.execute('ALTER TABLE staff_invitations NO FORCE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE staff_invitations DISABLE ROW LEVEL SECURITY')
    op.execute('REVOKE SELECT, INSERT, UPDATE ON staff_invitations FROM clinos_app')
    op.drop_index('ix_staff_invitations_tenant_id', table_name='staff_invitations')
    op.drop_table('staff_invitations')
