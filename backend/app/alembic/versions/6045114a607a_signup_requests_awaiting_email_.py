"""signup requests awaiting email verification

Revision ID: 6045114a607a
Revises: 94d4331e9eb0
Create Date: 2026-10-08 14:15:21.135155

Organisation signup verified by email
(`docs/reference/decisions/D-007-signup-email-verification.md`): a signup writes one row here and
nothing else; the emailed link turns it into the organisation, the account and the owner's grant, and
deletes every row for the address. Expired rows are deleted by the next signup.

**Not a tenant table**, so no RLS: no organisation exists yet, exactly like the legacy `user` table
the row becomes. The `users_roles` service is the only reader.

Grants: `clinos_app` may `SELECT, INSERT, UPDATE` (a resend replaces the link) **and `DELETE`**: a
request is transient working state, not a record, and deleting it is how a password verifier that was
never used stops being stored (at verification, and at expiry). `TRUNCATE` is not granted. The
no-hard-delete rule covers tables that carry a `tenant_id`; this one has none by construction.

No backfill and nothing to migrate: the table starts empty. The downgrade drops pending requests,
which only means those people sign up again.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '6045114a607a'
down_revision = '94d4331e9eb0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('signup_requests',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('email_key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('full_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('clinic_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('hashed_password', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('link_id', sa.Uuid(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('send_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('expires_at > sent_at', name=op.f('ck_signup_requests_expiry_after_send')),
    sa.CheckConstraint('send_count >= 1', name=op.f('ck_signup_requests_send_count_positive')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signup_requests'))
    )
    op.create_index('ix_signup_requests_email_key', 'signup_requests', ['email_key'], unique=False)
    op.create_index('ix_signup_requests_expires_at', 'signup_requests', ['expires_at'], unique=False)

    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON signup_requests TO clinos_app')
    op.execute('REVOKE TRUNCATE ON signup_requests FROM clinos_app')


def downgrade():
    op.execute('REVOKE SELECT, INSERT, UPDATE, DELETE ON signup_requests FROM clinos_app')
    op.drop_index('ix_signup_requests_expires_at', table_name='signup_requests')
    op.drop_index('ix_signup_requests_email_key', table_name='signup_requests')
    op.drop_table('signup_requests')
