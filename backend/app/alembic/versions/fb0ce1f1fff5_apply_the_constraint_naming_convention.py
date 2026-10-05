"""apply the constraint naming convention

Revision ID: fb0ce1f1fff5
Revises: 706856e36a80
Create Date: 2026-10-05 13:02:18.474315

Renames the constraints that predate `app.core.metadata`. The convention renders
primary keys as `pk_<table>` and foreign keys as
`fk_<table>_<column>_<referred table>`, and Postgres had named them `<table>_pkey`
and `<table>_column_fkey`.

Indexes and check constraints already match the convention, so they are untouched:
`ix_user_email` and `ix_tenants_slug` follow `ix_%(column_0_label)s`, and the
`tenants` checks were declared with suffixes, so they render as `ck_tenants_status`
and `ck_tenants_slug_lowercase` exactly as before.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'fb0ce1f1fff5'
down_revision = '706856e36a80'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE "user" RENAME CONSTRAINT user_pkey TO pk_user')
    op.execute('ALTER TABLE item RENAME CONSTRAINT item_pkey TO pk_item')
    op.execute(
        'ALTER TABLE item RENAME CONSTRAINT item_owner_id_fkey '
        'TO fk_item_owner_id_user'
    )
    op.execute('ALTER TABLE tenants RENAME CONSTRAINT tenants_pkey TO pk_tenants')


def downgrade():
    op.execute('ALTER TABLE tenants RENAME CONSTRAINT pk_tenants TO tenants_pkey')
    op.execute(
        'ALTER TABLE item RENAME CONSTRAINT fk_item_owner_id_user '
        'TO item_owner_id_fkey'
    )
    op.execute('ALTER TABLE item RENAME CONSTRAINT pk_item TO item_pkey')
    op.execute('ALTER TABLE "user" RENAME CONSTRAINT pk_user TO user_pkey')
