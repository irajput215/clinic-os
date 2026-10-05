"""link users to a tenant

Revision ID: 0bc1f345552b
Revises: 89d27ee38a6f
Create Date: 2026-10-05 16:11:09.683066

Step ① of `docs/reference/business-flow.md`: a signup can register an organisation, so
an account needs a link to it. The column is nullable because the platform
administrator predates tenancy, and `tenants` is global rather than row-secured — this
is a link, not yet an isolation boundary.

`ON DELETE SET NULL` because closing an organisation must not fail on an account that
still points at it.
"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '0bc1f345552b'
down_revision = '89d27ee38a6f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user', sa.Column('tenant_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_user_tenant_id'), 'user', ['tenant_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_user_tenant_id_tenants'),
        'user',
        'tenants',
        ['tenant_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint(op.f('fk_user_tenant_id_tenants'), 'user', type_='foreignkey')
    op.drop_index(op.f('ix_user_tenant_id'), table_name='user')
    op.drop_column('user', 'tenant_id')
